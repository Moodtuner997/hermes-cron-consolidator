"""``cron/executions.db`` is read without leaving or changing anything next to it (issue #2)."""

import hashlib
import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from cron_consolidator import analysis, report

from conftest import NOW, job

RECENT = (NOW - timedelta(days=1)).isoformat()


def make_ledger(folder: Path, *, wal: bool = True, rows: int = 1, keep_open: bool = False):
    """A table shaped like Hermes' ``executions``; closed (no sidecars left) unless ``keep_open``."""
    folder.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(folder / "executions.db")
    if wal:
        con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE executions (id TEXT, job_id TEXT, status TEXT, claimed_at TEXT)")
    for n in range(rows):
        con.execute("INSERT INTO executions VALUES (?, 'j1', 'failed', ?)", (str(n), RECENT))
    con.commit()
    if keep_open:
        con.execute("PRAGMA wal_autocheckpoint=0")
        return con
    con.close()
    return None


def listing(folder: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()}


def test_wal_ledger_without_sidecars_stays_as_it_was(tmp_path):
    make_ledger(tmp_path / "cron")
    before = listing(tmp_path / "cron")
    assert sorted(before) == ["executions.db"]
    assert analysis.load_failed_runs(tmp_path / "cron", 14, NOW) == {"j1": 1}
    assert listing(tmp_path / "cron") == before


def test_a_hash_a_percent_and_a_space_in_the_path(tmp_path):
    folder = tmp_path / "my profile #2 100%25" / "cron"
    make_ledger(folder)
    before = listing(folder)
    assert analysis.load_failed_runs(folder, 14, NOW) == {"j1": 1}
    assert listing(folder) == before
    assert sorted(p.name for p in folder.parent.parent.iterdir()) == ["my profile #2 100%25"]  # no stray file


def test_a_live_writer_is_read_including_pages_not_yet_flushed(tmp_path):
    writer = make_ledger(tmp_path / "cron", rows=1, keep_open=True)
    try:
        writer.execute("INSERT INTO executions VALUES ('x', 'j1', 'failed', ?)", (RECENT,))
        writer.commit()
        before = sorted(listing(tmp_path / "cron"))
        assert "executions.db-wal" in before
        assert analysis.load_failed_runs(tmp_path / "cron", 14, NOW) == {"j1": 2}
        assert sorted(listing(tmp_path / "cron")) == before
    finally:
        writer.close()


def test_rollback_journal_ledger_is_unchanged_too(tmp_path):
    make_ledger(tmp_path / "cron", wal=False)
    before = listing(tmp_path / "cron")
    assert analysis.load_failed_runs(tmp_path / "cron", 14, NOW) == {"j1": 1}
    assert listing(tmp_path / "cron") == before


def test_read_only_ledger_file(tmp_path):
    make_ledger(tmp_path / "cron")
    db = tmp_path / "cron" / "executions.db"
    db.chmod(0o444)
    try:
        assert analysis.load_failed_runs(tmp_path / "cron", 14, NOW) == {"j1": 1}
        assert sorted(listing(tmp_path / "cron")) == ["executions.db"]
    finally:
        db.chmod(0o644)


def test_an_unreadable_ledger_gives_no_counts_instead_of_an_error(tmp_path):
    (tmp_path / "cron").mkdir()
    (tmp_path / "cron" / "executions.db").write_bytes(b"not a database at all, just text")
    assert analysis.load_failed_runs(tmp_path / "cron", 14, NOW) == {}


def test_the_report_over_a_wal_profile_leaves_its_cron_folder_alone(make_home):
    home = Path(make_home([job("j1", "a", "x" * 40, failure_streak=4)], audit=[("j1", 1, 10, 1)]))
    make_ledger(home / "cron")
    before = listing(home / "cron")
    data = json.loads(report.run(home, "report --json", now=NOW))
    assert data["failing"][0]["failed_runs_in_window"] == 1
    assert listing(home / "cron") == before


@pytest.mark.parametrize("as_json", [False, True])
def test_prompt_text_is_never_printed(make_home, as_json):
    marker = "words only found in the prompt"
    base = "Summarise the unread newsletters in my inbox and send a digest of what concerns my projects. "
    home = make_home([job("j1", "a", base + marker), job("j2", "b", base + marker + " again", "0 8 * * tue")])
    out = report.run(Path(home), "report --json" if as_json else "report", now=NOW)
    assert "Merge candidates (1)" in out or '"merge_candidates"' in out  # the prompts were compared...
    assert marker not in out  # ...and never shown
