"""End-to-end check against a real Hermes install, without any LLM.

Run with the Hermes interpreter and a throwaway HERMES_HOME in which the plugin is installed and enabled:

    HERMES_HOME=<home> <hermes python> tests/e2e_hermes.py

It loads the plugin through Hermes' own discovery, runs ``/cron-consolidator`` through the registered command
handler and ``hermes cron-consolidator`` through the real CLI parser, on the synthetic profile from
``make_demo_profile.py``, and checks that neither route changes a byte of the profile's ``cron/`` folder.
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
before = snapshot(cron)
check("the demo profile holds jobs.json and usage_audit.jsonl", sorted(before) == ["jobs.json", "usage_audit.jsonl"],
      repr(sorted(before)))

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
data = json.loads(slash("report --json --days 30", session_id="e2e-session"))
check("--json --days gives the same plan as data", data["window_days"] == 30 and data["jobs"]["enabled"] == 14
      and data["after_merge"] == 9 and len(data["merge_candidates"]) == 3, json.dumps(data)[:300])
check("a bad argument is refused with the help text", "unknown argument" in slash("report --apply"))

hermes_main = str(Path(hermes_cli.__file__).resolve().parent / "main.py")
shell = subprocess.run([sys.executable, hermes_main, "cron-consolidator", "report", "--json"],
                       capture_output=True, text=True, encoding="utf-8", timeout=180, env=os.environ.copy())
check("hermes cron-consolidator exits 0 through the real CLI parser", shell.returncode == 0,
      f"exit {shell.returncode}: {shell.stderr[-400:]}")
try:
    from_cli = json.loads(shell.stdout[shell.stdout.index("{"):])
except ValueError:
    from_cli = {}
check("the CLI route returns the same plan as JSON", from_cli.get("after_merge") == 9
      and from_cli.get("jobs", {}).get("enabled") == 14, shell.stdout[:300])
shell = subprocess.run([sys.executable, hermes_main, "cron-consolidator", "report", "--days", "0"],
                       capture_output=True, text=True, encoding="utf-8", timeout=180, env=os.environ.copy())
check("the CLI route reports a bad option as text", "--days needs a positive number" in shell.stdout, shell.stdout[:300])

after = snapshot(cron)
changed = sorted(set(before) ^ set(after)) + sorted(k for k in before if k in after and before[k] != after[k])
check("neither route touched the profile's cron folder", not changed, f"changed or new: {changed}")

print("\nFAILED: " + ", ".join(failures) if failures else "\nAll checks passed")
sys.exit(1 if failures else 0)
