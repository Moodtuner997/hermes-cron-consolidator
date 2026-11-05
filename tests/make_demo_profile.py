"""Write a synthetic Hermes profile with a crowded cron list, for the README and the demo.

    python tests/make_demo_profile.py DEST

Then: ``hermes cron-consolidator report --home DEST``. All names and prompts are invented.
"""

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW = datetime.now(timezone.utc)

DIGEST = "Read the unread newsletters in my inbox, keep what touches my open projects and send me a short digest."
PRS = "List the open pull requests on {repo} that have had no activity for a week and ask the author for a status."
INVOICE = "Check the finance mailbox for new supplier invoices and add each one to the payables sheet."

JOBS = [
    ("digest-mon", DIGEST + " Focus on Monday's launches.", "0 8 * * mon", ["gmail"], "telegram"),
    ("digest-wed", DIGEST + " Focus on tooling news.", "0 8 * * wed", ["gmail"], "telegram"),
    ("digest-fri", DIGEST + " Focus on funding rounds.", "0 8 * * fri", ["gmail"], "telegram"),
    ("stale-prs-api", PRS.format(repo="the API repository"), "0 9 * * *", ["github"], "slack"),
    ("stale-prs-web", PRS.format(repo="the website repository"), "0 9 * * *", ["github"], "slack"),
    ("stale-prs-docs", PRS.format(repo="the docs repository"), "0 9 * * *", ["github"], "slack"),
    ("invoices-morning", INVOICE, "30 7 * * 1-5", ["gmail", "sheets"], "slack"),
    ("invoices-evening", INVOICE + " Flag anything above 5000 euros.", "30 18 * * 1-5", ["gmail", "sheets"], "slack"),
    ("backup-check", "Verify that last night's backup completed and report its size and duration.", "15 6 * * *", [], "telegram"),
    ("disk-watch", "Check disk usage on the build server and warn me above eighty percent.", "*/30 * * * *", [], "telegram"),
    ("weather", "Tell me if I need an umbrella in Lyon today.", "0 7 * * *", [], "telegram"),
    ("rates", "Fetch the euro-dollar rate and post it to the finance channel.", "0 9 * * 1-5", [], "slack"),
    ("standup-notes", "Prepare yesterday's standup notes from the team channel history.", "0 9 * * 1-5", ["slack"], "local"),
    ("changelog", "Draft this week's changelog from merged pull requests.", "0 16 * * fri", ["github"], "local"),
]


def build(dest: Path) -> None:
    rng = random.Random(7)
    cron = dest / "cron"
    cron.mkdir(parents=True, exist_ok=True)
    rows, audit = [], []
    for n, (name, prompt, expr, skills, deliver) in enumerate(JOBS):
        job_id = f"{n + 1:012x}"
        rec = {"id": job_id, "name": name, "prompt": prompt, "skills": skills, "deliver": deliver,
               "schedule": {"kind": "cron", "expr": expr}, "schedule_display": expr, "enabled": True,
               "created_at": (NOW - timedelta(days=60 - n)).isoformat(), "failure_streak": 0}
        if name == "rates":
            rec.update(failure_streak=5, last_error="HTTP 502 from the exchange-rate API")
        if name == "weather":
            rec["last_delivery_unverified"] = ["telegram:accepted-without-receipt"]
        rows.append(rec)
        if name == "disk-watch":
            per_day = 48
        elif "*" in expr.split()[4] or expr.split()[4].startswith("1-5"):
            per_day = 1
        else:
            per_day = 0.3
        for day in range(14):
            for _ in range(int(per_day) + (1 if rng.random() < per_day % 1 else 0)):
                ts = (NOW - timedelta(days=day, hours=rng.random() * 20)).isoformat().replace("+00:00", "Z")
                audit.append(json.dumps({"ts": ts, "job_id": job_id, "prompt_tokens": 1800 + rng.randint(0, 900),
                                         "completion_tokens": 250 + rng.randint(0, 200),
                                         "response_silent": False, "deliver_target": deliver}))
    (cron / "jobs.json").write_text(json.dumps({"jobs": rows}, indent=1), encoding="utf-8")
    (cron / "usage_audit.jsonl").write_text("\n".join(audit) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build(Path(sys.argv[1]))
    print(f"wrote {sys.argv[1]}")
