"""Text interface shared by ``/cron-consolidator`` (in a session) and ``hermes cron-consolidator`` (shell)."""

from __future__ import annotations

import json
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any

from . import analysis

HELP = (
    "cron-consolidator: read-only plan for merging and rescheduling cron jobs.\n"
    "  report [--json] [--days N] [--profile NAME] [--home PATH]\n"
    "Nothing is changed: the plan lists what could be merged, which jobs fire in the same minute, which\n"
    "keep failing and which deliveries were never confirmed. Token figures come from usage_audit.jsonl."
)


def _name(item: dict[str, Any]) -> str:
    return f"`{item['name']}`" if item.get("name") else f"`{item['id']}`"


def render(result: dict[str, Any]) -> str:
    jobs = result["jobs"]
    out = [
        "# Cron consolidation plan",
        "",
        f"{jobs['enabled']} enabled job(s) of {jobs['total']}; {jobs['with_usage_data']} with token data in the "
        f"last {result['window_days']} days. Merging every candidate below would leave **{result['after_merge']}**.",
        "Read-only: nothing was changed.",
    ]
    merges = result["merge_candidates"]
    out += ["", f"## Merge candidates ({len(merges)})"]
    if not merges:
        out.append("None found.")
    for n, m in enumerate(merges, 1):
        keep = m["keep"]
        out.append(f"\n{n}. Keep {_name(keep)} ({keep['schedule']}) and fold in {len(m['fold_in'])} job(s):")
        for f in m["fold_in"]:
            out.append(f"   - {_name(f)} ({f['schedule']}): {'; '.join(f['why'])}")
        if m["skills"]:
            out.append(f"   Skills to carry over: {', '.join(m['skills'])}")
        s = m["saving"]
        if s:
            out.append(f"   Up to {s['prompt_tokens_per_day_ceiling']:,} prompt tokens/day (ceiling: the merged "
                       "prompt is longer, output tokens not counted).")
        else:
            out.append("   No token data for these jobs, so no saving is claimed.")
    col = result["slot_collisions"]
    out += ["", f"## Clock-time jobs that fire in the same minute ({len(col)})"]
    if not col:
        out.append("None found.")
    for g in col:
        when = g["slot"] if len(g["slots"]) == 1 else f"{g['slot']} (and {len(g['slots']) - 1} other time(s))"
        out.append(f"- at {when}: " + ", ".join(f"{_name(j)} ({j['schedule']})" for j in g["jobs"]))
    out += ["", f"## Failing jobs ({len(result['failing'])})"]
    out += [f"- {_name(f)}: {f['streak']} failures in a row"
            + (f"; last error: {f['error']}" if f["error"] else "") for f in result["failing"]] or ["None."]
    out += ["", f"## Deliveries never confirmed ({len(result['unverified_delivery'])})"]
    out += [f"- {_name(u)} -> {u['deliver']}" for u in result["unverified_delivery"]] or ["None."]
    if result["untimed"]:
        out += ["", "## Schedules not understood (left out of the collision check)"]
        out += [f"- {_name(u)}: {u['schedule']}" for u in result["untimed"]]
    return "\n".join(out)


def _cron_dir(hermes_home: Path, profile: str | None, home: str | None) -> Path:
    if home:
        return Path(home).expanduser() / "cron"
    if profile:
        root = hermes_home.parent.parent if hermes_home.parent.name == "profiles" else hermes_home
        return root / "profiles" / profile / "cron"
    return hermes_home / "cron"


def run(hermes_home: Path, raw_args: str = "", now: datetime | None = None) -> str:
    try:
        tokens = shlex.split(raw_args, posix=False) if isinstance(raw_args, str) else list(raw_args)
    except ValueError as exc:
        return f"cron-consolidator: {exc}\n{HELP}"
    if tokens and tokens[0] == "report":
        tokens = tokens[1:]
    elif tokens and tokens[0] in ("help", "-h", "--help"):
        return HELP
    as_json, days, profile, home = False, 14, None, None
    it = iter(tokens)
    for tok in it:
        tok = tok.strip("\"'")
        if tok == "--json":
            as_json = True
        elif tok in ("--days", "--profile", "--home"):
            val = next(it, "").strip("\"'")
            if tok == "--days":
                if not val.isdigit() or not int(val):
                    return f"cron-consolidator: --days needs a positive number\n{HELP}"
                days = int(val)
            elif tok == "--profile":
                profile = val
            else:
                home = val
        else:
            return f"cron-consolidator: unknown argument {tok!r}\n{HELP}"
    cron_dir = _cron_dir(hermes_home, profile, home)
    if not (cron_dir / "jobs.json").is_file():
        return f"cron-consolidator: no cron/jobs.json under {cron_dir.parent} (is the profile name right?)"
    try:
        result = analysis.analyze(cron_dir, days=days, now=now)
    except (OSError, ValueError) as exc:
        return f"cron-consolidator: could not read {cron_dir / 'jobs.json'}: {exc}"
    return json.dumps(result, indent=2, ensure_ascii=False) if as_json else render(result)
