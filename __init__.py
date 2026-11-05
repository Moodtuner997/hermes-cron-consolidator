"""cron-consolidator: a read-only plan for merging and rescheduling Hermes cron jobs.

Registers the ``/cron-consolidator`` slash command and the ``hermes cron-consolidator`` CLI command. It
hooks nothing and changes nothing: it reads ``cron/jobs.json``, ``cron/usage_audit.jsonl`` and
``cron/executions.db`` of the chosen profile.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import report


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def _slash(raw_args: str = "", **_: Any) -> str:
    return report.run(_hermes_home(), raw_args)


def _cli_setup(parser: Any) -> None:
    import argparse

    parser.add_argument("rest", nargs=argparse.REMAINDER,
                        help="report [--json] [--days N] [--profile NAME] [--home PATH]")


def _cli_run(args: Any) -> None:
    print(report.run(_hermes_home(), list(getattr(args, "rest", []) or ["report"])))


def register(ctx: Any) -> None:
    ctx.register_command("cron-consolidator", _slash,
                         description="Plan merges for overlapping cron jobs (read-only)",
                         args_hint="[report] [--json] [--days N] [--profile NAME]")
    ctx.register_cli_command("cron-consolidator", "Plan merges for overlapping cron jobs (read-only)",
                             _cli_setup, _cli_run)
