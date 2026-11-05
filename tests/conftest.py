import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# The plugin directory is a package (hyphenated repo name): load it under a fixed name.
spec = importlib.util.spec_from_file_location(
    "cron_consolidator", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
)
module = importlib.util.module_from_spec(spec)
sys.modules["cron_consolidator"] = module
spec.loader.exec_module(module)

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def job(id, name, prompt, expr="0 9 * * *", skills=(), deliver="telegram", **extra):
    rec = {"id": id, "name": name, "prompt": prompt, "skills": list(skills), "deliver": deliver,
           "schedule": {"kind": "cron", "expr": expr}, "schedule_display": expr, "enabled": True,
           "created_at": f"2026-10-{int(id[1:]) % 28 + 1:02d}T08:00:00+00:00", "failure_streak": 0}
    rec.update(extra)
    return rec


@pytest.fixture
def make_home(tmp_path):
    """Build a fake profile: ``make_home(jobs, audit=[...])`` returns the profile directory."""

    def build(jobs, audit=()):
        cron = tmp_path / "cron"
        cron.mkdir(exist_ok=True)
        (cron / "jobs.json").write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
        lines = []
        for job_id, days_ago, prompt_tokens, completion_tokens in audit:
            ts = (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
            lines.append(json.dumps({"ts": ts, "job_id": job_id, "prompt_tokens": prompt_tokens,
                                     "completion_tokens": completion_tokens, "response_silent": False}))
        (cron / "usage_audit.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return tmp_path

    return build
