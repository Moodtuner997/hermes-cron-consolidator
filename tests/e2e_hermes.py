"""End-to-end check against a real Hermes install, without any LLM.

Run with the Hermes interpreter and a throwaway HERMES_HOME in which the plugin is installed and enabled:

    HERMES_HOME=<home> <hermes python> tests/e2e_hermes.py

It loads the plugin through Hermes' own discovery, runs ``/cron-consolidator`` through the registered command
handler and ``hermes cron-consolidator`` through the real CLI parser, on the synthetic profile from
``make_demo_profile.py`` plus a failed run written by Hermes' own execution ledger (WAL mode), and checks that
neither route changes, adds or removes a file of the profile's ``cron/`` folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import hermes_cli
from hermes_cli.plugins import discover_plugins, get_plugin_command_handler, get_plugin_manager

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_demo_profile  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + label + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def snapshot(folder: Path) -> dict[str, str]:
    """Every file under ``folder`` with its content hash, so a new, removed or changed file shows up."""
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


home = Path(os.environ["HERMES_HOME"])
make_demo_profile.build(home)
cron = home / "cron"

# Hermes writes absolute paths into a job's last error (a missing script, say): give the failing demo job one.
jobs_file = cron / "jobs.json"
doc = json.loads(jobs_file.read_text(encoding="utf-8"))
for rec in doc["jobs"]:
    if rec.get("name") == "rates":
        rec["last_error"] = f"Script not found: {home / 'scripts' / 'rates.py'} (looked in {home})"
jobs_file.write_text(json.dumps(doc), encoding="utf-8")

# A failed run of the demo's "rates" job, written by Hermes' own ledger so the real schema and journal mode are used.
import cron.executions as executions  # noqa: E402

executions.EXECUTIONS_FILE = cron / "executions.db"
attempt = executions.create_execution("00000000000c", source="e2e")
executions.finish_execution(attempt["id"], success=False, error="HTTP 502 from the exchange-rate API")
before = snapshot(cron)
print("profile cron/ before:", sorted(before))
check("the profile holds jobs.json, usage_audit.jsonl and Hermes' executions.db",
      {"jobs.json", "usage_audit.jsonl", "executions.db"} <= set(before), repr(sorted(before)))

discover_plugins(force=True)
mine = [p for p in get_plugin_manager().list_plugins() if p["name"] == "cron-consolidator"]
check("Hermes discovers and enables the plugin without error", len(mine) == 1 and mine[0]["enabled"]
      and not mine[0]["error"], repr(mine)[:300])
check("it registers one command and no tool, hook or middleware",
      bool(mine) and (mine[0]["tools"], mine[0]["hooks"], mine[0]["middleware"], mine[0]["commands"]) == (0, 0, 0, 1),
      repr(mine)[:300])

slash = get_plugin_command_handler("cron-consolidator")
check("the slash command handler is registered", callable(slash))
if not callable(slash):
    sys.exit("FAILED: " + ", ".join(failures))
text = slash("", session_id="e2e-session")
check("/cron-consolidator reads the active profile and says it changed nothing",
      "# Cron consolidation plan" in text and "Read-only: nothing was changed." in text, text[:300])
check("it finds the three merges of the demo profile", "## Merge candidates (3)" in text and "leave **9**" in text,
      text[:500])
check("it names the failing job and the unconfirmed delivery",
      "`rates`: 5 failures in a row" in text and "## Deliveries never confirmed (1)" in text, text[-600:])
raw_json = slash("report --json --days 30", session_id="e2e-session")
data = json.loads(raw_json)
check("--json --days gives the same plan as data", data["window_days"] == 30 and data["jobs"]["enabled"] == 14
      and data["after_merge"] == 9 and len(data["merge_candidates"]) == 3, json.dumps(data)[:300])
check("the failed run in Hermes' ledger is counted for the failing job",
      [f["failed_runs_in_window"] for f in data["failing"]] == [1], json.dumps(data["failing"])[:300])
check("a bad argument is refused with the help text", "unknown argument" in slash("report --apply"))
check("a chat refuses --home and a profile that is a path (0.1.2)",
      "available from the shell only" in slash(f"report --home {home}")
      and "takes a profile name" in slash("report --profile ../.."), "")
chat_missing = slash("report --profile nope")
check("a chat error names the profile and not the server path (0.1.2)",
      "no cron/jobs.json for profile 'nope'" in chat_missing
      and str(home) not in chat_missing and home.as_posix() not in chat_missing, chat_missing)
check("a chat's JSON carries no server path and no warning over a readable ledger (0.1.2)",
      "profile_cron_dir" not in data and data["warnings"] == [], json.dumps(data)[:300])
leaks = (str(home), home.as_posix(), json.dumps(str(home))[1:-1])
check("a chat shows <path> where a job's last error held a path, in the text and in the JSON (0.1.3)",
      "last error: Script not found: <path>" in text and data["failing"][0]["error"].startswith("Script not found: <path>")
      and not any(p in text or p in raw_json for p in leaks), text[-500:])
check("a chat refuses a --days outside 1 to 3650 as text (0.1.3)",
      all("--days needs a number from 1 to 3650" in slash(f"report --days {v}") for v in ("0", "3651", "99999999999")), "")

hermes_main = str(Path(hermes_cli.__file__).resolve().parent / "main.py")
shell = subprocess.run([sys.executable, hermes_main, "cron-consolidator", "report", "--json"],
                       capture_output=True, text=True, encoding="utf-8", timeout=180, env=os.environ.copy())
check("hermes cron-consolidator exits 0 through the real CLI parser", shell.returncode == 0,
      f"exit {shell.returncode}: {shell.stderr[-400:]}")
try:
    from_cli = json.loads(shell.stdout[shell.stdout.index("{"):])
except ValueError:
    from_cli = {}
check("the CLI route returns the same plan as JSON, ledger count included", from_cli.get("after_merge") == 9
      and from_cli.get("jobs", {}).get("enabled") == 14
      and [f["failed_runs_in_window"] for f in from_cli.get("failing", [])] == [1], shell.stdout[:300])
check("the shell route keeps the profile folder in its JSON", from_cli.get("profile_cron_dir") == str(cron), repr(from_cli.get("profile_cron_dir")))
check("the shell route keeps the paths of a job's last error (0.1.3)",
      bool(from_cli.get("failing")) and str(home) in from_cli["failing"][0]["error"], repr(from_cli.get("failing"))[:300])
shell = subprocess.run([sys.executable, hermes_main, "cron-consolidator", "report", "--json", "--home", str(home)],
                       capture_output=True, text=True, encoding="utf-8", timeout=180, env=os.environ.copy())
check("the shell route still takes --home (0.1.2)", '"after_merge": 9' in shell.stdout, shell.stdout[:300])
nowhere = home / "nowhere"  # Hermes' own parser takes --profile before the plugin sees it, so the shell route is tried with --home
shell = subprocess.run([sys.executable, hermes_main, "cron-consolidator", "report", "--home", str(nowhere)],
                       capture_output=True, text=True, encoding="utf-8", timeout=180, env=os.environ.copy())
check("the shell route says where it looked when a folder has no jobs.json (0.1.2)",
      "no cron/jobs.json under" in shell.stdout and str(nowhere) in shell.stdout, shell.stdout[:300])
shell = subprocess.run([sys.executable, hermes_main, "cron-consolidator", "report", "--days", "0"],
                       capture_output=True, text=True, encoding="utf-8", timeout=180, env=os.environ.copy())
check("the CLI route reports a bad option as text", "--days needs a number from 1 to 3650" in shell.stdout, shell.stdout[:300])

after = snapshot(cron)
changed = sorted(set(before) ^ set(after)) + sorted(k for k in before if k in after and before[k] != after[k])
print("profile cron/ after: ", sorted(after))
check("neither route changed, added or removed a file in the profile's cron folder", not changed,
      f"changed or new: {changed}")

print("\nFAILED: " + ", ".join(failures) if failures else "\nAll checks passed")
sys.exit(1 if failures else 0)
