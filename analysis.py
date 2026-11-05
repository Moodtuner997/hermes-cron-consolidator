"""Read a Hermes profile's cron data and work out which jobs could be merged or rescheduled.

Everything here is read-only and deterministic: no model call, no network. Inputs are ``cron/jobs.json``
(required), ``cron/usage_audit.jsonl`` and ``cron/executions.db`` (both optional). Output is a plain dict
that ``report.py`` renders as Markdown or JSON.
"""

from __future__ import annotations

import difflib
import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import cronfields

DUP_THRESHOLD = 0.85
MIN_PROMPT_CHARS = 20
FAIL_STREAK = 3
FIXED_MAX_PER_DAY = 6  # more frequent than this counts as a poller, not a clock-time job
MAX_JOBS = 400  # pairwise prompt comparison is quadratic: past this only the cheap checks run


@dataclass
class Job:
    id: str
    name: str
    prompt: str
    skills: tuple[str, ...]
    deliver: str
    model: str | None
    enabled: bool
    no_agent: bool
    script: str
    kind: str
    display: str
    created_at: str
    failure_streak: int
    last_error: str | None
    unverified: bool
    timing: tuple[frozenset[int], ...] | None = None
    fires_per_day: float | None = None
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.name} ({self.id})" if self.name else self.id


def _norm_prompt(text: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", text.lower())).strip()


def _job_from(raw: dict[str, Any]) -> Job | None:
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    sched = raw.get("schedule") if isinstance(raw.get("schedule"), dict) else {}
    kind = str(sched.get("kind") or "")
    timing = per_day = None
    if kind == "cron" and sched.get("expr"):
        try:
            timing = cronfields.parse(str(sched["expr"]))
            per_day = cronfields.fires_per_day(timing)
        except (ValueError, KeyError):
            timing = None
    elif kind == "interval" and sched.get("minutes"):
        try:
            per_day = 1440 / max(1, int(sched["minutes"]))
        except (TypeError, ValueError):
            per_day = None
    skills = raw.get("skills") or ([raw["skill"]] if raw.get("skill") else [])
    return Job(
        id=str(raw["id"]),
        name=str(raw.get("name") or ""),
        prompt=str(raw.get("prompt") or ""),
        skills=tuple(sorted(str(s) for s in skills)),
        deliver=str(raw.get("deliver") or "local"),
        model=raw.get("model"),
        enabled=bool(raw.get("enabled", True)),
        no_agent=bool(raw.get("no_agent")),
        script=str(raw.get("script") or ""),
        kind=kind,
        display=str(raw.get("schedule_display") or sched.get("expr") or kind),
        created_at=str(raw.get("created_at") or ""),
        failure_streak=int(raw.get("failure_streak") or 0),
        last_error=raw.get("last_error"),
        unverified=bool(raw.get("last_delivery_unverified")),
        timing=timing,
        fires_per_day=per_day,
    )


def load_jobs(cron_dir: Path) -> list[Job]:
    data = json.loads((cron_dir / "jobs.json").read_text(encoding="utf-8-sig"))
    rows = data.get("jobs", []) if isinstance(data, dict) else data
    jobs = [j for j in (_job_from(r) for r in rows if isinstance(r, dict)) if j]
    return jobs


def _parse_ts(text: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_usage(cron_dir: Path, days: int, now: datetime) -> dict[str, dict[str, Any]]:
    """Per-job totals from ``usage_audit.jsonl`` over the last ``days`` days."""
    path = cron_dir / "usage_audit.jsonl"
    cutoff = now - timedelta(days=days)
    out: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"fires": 0, "prompt_tokens": 0, "completion_tokens": 0, "silent": 0, "errors": 0})
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            ts = _parse_ts(rec.get("ts", "")) if isinstance(rec, dict) else None
            if ts is None or ts < cutoff or not rec.get("job_id"):
                continue
            u = out[str(rec["job_id"])]
            u["fires"] += 1
            u["prompt_tokens"] += int(rec.get("prompt_tokens") or 0)
            u["completion_tokens"] += int(rec.get("completion_tokens") or 0)
            u["silent"] += 1 if rec.get("response_silent") else 0
            u["errors"] += 1 if rec.get("error") else 0
    return dict(out)


def load_failed_runs(cron_dir: Path, days: int, now: datetime) -> dict[str, int]:
    """Failed and missed executions per job from ``executions.db`` (opened read-only)."""
    path = cron_dir / "executions.db"
    if not path.is_file():
        return {}
    cutoff = (now - timedelta(days=days)).isoformat()
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2)
        try:
            rows = con.execute(
                "SELECT job_id, COUNT(*) FROM executions WHERE status IN ('failed','missed') "
                "AND claimed_at >= ? GROUP BY job_id", (cutoff,)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return {}
    return {str(j): int(n) for j, n in rows}


class _Groups:
    def __init__(self, keys: list[str]):
        self.parent = {k: k for k in keys}

    def find(self, k: str) -> str:
        while self.parent[k] != k:
            self.parent[k] = self.parent[self.parent[k]]
            k = self.parent[k]
        return k

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)

    def components(self) -> list[list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for k in self.parent:
            out[self.find(k)].append(k)
        return [v for v in out.values() if len(v) > 1]


def _collisions(jobs: list[Job]) -> list[dict[str, Any]]:
    """Fixed-time cron jobs that fire in the same minute, one entry per clock time, biggest first.

    Pollers (more than ``FIXED_MAX_PER_DAY`` firings a day, such as ``*/30``) touch every slot, so they
    are left out: lumping them in would chain unrelated jobs into one group.
    """
    fixed = [j for j in jobs if j.enabled and j.timing and len(j.timing[0]) * len(j.timing[1]) <= FIXED_MAX_PER_DAY]
    by_slot: dict[tuple[int, int], list[Job]] = defaultdict(list)
    for j in fixed:
        for h in j.timing[1]:
            for m in j.timing[0]:
                by_slot[(h, m)].append(j)
    found: dict[frozenset[str], dict[str, Any]] = {}
    for (h, m), members in sorted(by_slot.items()):
        if len(members) < 2:
            continue
        groups = _Groups([j.id for j in members])
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                if cronfields.overlap(a.timing, b.timing):
                    groups.union(a.id, b.id)
        by_id = {j.id: j for j in members}
        for comp in groups.components():
            key = frozenset(comp)
            entry = found.setdefault(key, {"slot": f"{h:02d}:{m:02d}", "slots": [], "jobs": [
                {"id": i, "name": by_id[i].name, "schedule": by_id[i].display} for i in sorted(comp)]})
            entry["slots"].append(f"{h:02d}:{m:02d}")
    out = list(found.values())
    out.sort(key=lambda g: (-len(g["jobs"]), g["slot"]))
    return out


def _similar_pairs(jobs: list[Job]) -> list[tuple[Job, Job, float]]:
    cands = [(j, _norm_prompt(j.prompt)) for j in jobs if j.enabled and not j.no_agent]
    cands = [(j, p) for j, p in cands if len(p) >= MIN_PROMPT_CHARS]
    if len(cands) > MAX_JOBS:
        return []
    pairs = []
    for i, (a, pa) in enumerate(cands):
        for b, pb in cands[i + 1:]:
            if min(len(pa), len(pb)) / max(len(pa), len(pb)) < DUP_THRESHOLD:
                continue
            sm = difflib.SequenceMatcher(None, pa, pb, autojunk=False)
            if sm.real_quick_ratio() < DUP_THRESHOLD or sm.quick_ratio() < DUP_THRESHOLD:
                continue
            ratio = sm.ratio()
            if ratio >= DUP_THRESHOLD:
                pairs.append((a, b, ratio))
    return pairs


def _keeper(members: list[Job]) -> Job:
    return min(members, key=lambda j: (-j.usage.get("fires", 0), j.created_at or "~", j.id))


def _saving(keep: Job, others: list[Job]) -> dict[str, Any] | None:
    """Prompt-side tokens per day the merge could stop spending, from observed fires only.

    A merged job still carries a longer prompt, so this is a ceiling, not a forecast; completion tokens
    are left out because the merged run still has to produce its output.
    """
    per_day = 0.0
    seen = False
    for j in others:
        u = j.usage
        if u.get("fires") and u["prompt_tokens"]:
            seen = True
            per_day += u["prompt_tokens"] / u["window_days"]
    return {"prompt_tokens_per_day_ceiling": round(per_day)} if seen else None


def analyze(cron_dir: Path, days: int = 14, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    jobs = load_jobs(cron_dir)
    usage = load_usage(cron_dir, days, now)
    failed_runs = load_failed_runs(cron_dir, days, now)
    for j in jobs:
        u = usage.get(j.id, {})
        j.usage = dict(u, window_days=days, failed_runs=failed_runs.get(j.id, 0))
    enabled = [j for j in jobs if j.enabled]

    groups = _Groups([j.id for j in enabled])
    reasons: dict[str, set[str]] = defaultdict(set)
    for a, b, ratio in _similar_pairs(enabled):
        groups.union(a.id, b.id)
        reasons[a.id].add(f"prompt ~{ratio:.0%} like {b.name or b.id}")
        reasons[b.id].add(f"prompt ~{ratio:.0%} like {a.name or a.id}")
    by_role: dict[tuple[tuple[str, ...], str], list[Job]] = defaultdict(list)
    for j in enabled:
        if j.skills and not j.no_agent:
            by_role[(j.skills, j.deliver)].append(j)
    for (skills, deliver), members in by_role.items():
        for m in members[1:]:
            groups.union(members[0].id, m.id)
        if len(members) > 1:
            for m in members:
                reasons[m.id].add(f"same skills ({', '.join(skills)}) and destination ({deliver})")

    by_script: dict[str, list[Job]] = defaultdict(list)
    for j in enabled:
        if j.script:
            by_script[j.script].append(j)
    for script, members in by_script.items():
        if len(members) > 1:
            for m in members[1:]:
                groups.union(members[0].id, m.id)
            for m in members:
                reasons[m.id].add(f"runs the same script ({Path(script).name})")

    by_id = {j.id: j for j in enabled}
    merges = []
    for comp in groups.components():
        members = [by_id[i] for i in comp]
        keep = _keeper(members)
        others = [m for m in members if m.id != keep.id]
        merges.append({
            "keep": {"id": keep.id, "name": keep.name, "schedule": keep.display},
            "fold_in": [{"id": o.id, "name": o.name, "schedule": o.display,
                         "why": sorted(reasons[o.id])} for o in others],
            "skills": sorted({s for m in members for s in m.skills}),
            "saving": _saving(keep, others),
        })
    merges.sort(key=lambda m: -len(m["fold_in"]))

    fewer = sum(len(m["fold_in"]) for m in merges)
    return {
        "profile_cron_dir": str(cron_dir),
        "window_days": days,
        "jobs": {"total": len(jobs), "enabled": len(enabled),
                 "with_usage_data": sum(1 for j in jobs if j.usage.get("fires"))},
        "after_merge": len(enabled) - fewer,
        "merge_candidates": merges,
        "slot_collisions": _collisions(jobs),
        "failing": [{"id": j.id, "name": j.name, "streak": j.failure_streak, "error": (j.last_error or "")[:160],
                     "failed_runs_in_window": j.usage["failed_runs"]}
                    for j in enabled if j.failure_streak >= FAIL_STREAK],
        "unverified_delivery": [{"id": j.id, "name": j.name, "deliver": j.deliver}
                                for j in enabled if j.unverified],
        "untimed": [{"id": j.id, "name": j.name, "schedule": j.display}
                    for j in enabled if j.kind == "cron" and not j.timing],
    }
