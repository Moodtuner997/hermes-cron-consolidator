import json
import os
from pathlib import Path

from cron_consolidator import report

from conftest import NOW, job

DIGEST = "Summarise the unread newsletters in my inbox, keep only what concerns my projects, and send a digest."


def test_markdown_report_and_json(make_home):
    home = Path(make_home([job("j1", "digest-a", DIGEST + " A.", "0 8 * * mon"),
                           job("j2", "digest-b", DIGEST + " B.", "0 8 * * tue")],
                          audit=[("j2", 1, 1400, 100)]))
    text = report.run(home, "report", now=NOW)
    assert "Merge candidates (1)" in text and "`digest-a`" in text and "Read-only" in text
    assert "leave **1**" in text
    data = json.loads(report.run(home, "report --json", now=NOW))
    assert data["after_merge"] == 1 and data["jobs"]["enabled"] == 2


def test_profile_and_home_options(make_home, tmp_path):
    root = tmp_path / "root"
    prof = root / "profiles" / "work" / "cron"
    prof.mkdir(parents=True)
    (prof / "jobs.json").write_text(json.dumps({"jobs": [job("j1", "only", "x" * 40)]}), encoding="utf-8")
    assert "1 enabled job(s) of 1" in report.run(root, "report --profile work")
    assert "1 enabled job(s) of 1" in report.run(root / "profiles" / "other", "--profile work")
    assert "1 enabled job(s) of 1" in report.run(Path("nowhere"), f'--home "{root / "profiles" / "work"}"')


def test_clear_errors(tmp_path):
    assert "no cron/jobs.json" in report.run(tmp_path, "report --profile nope")
    assert "unknown argument" in report.run(tmp_path, "report --apply")
    assert "--days needs" in report.run(tmp_path, "report --days x")
    assert "read-only" in report.run(tmp_path, "help")


def test_never_writes_into_the_profile(make_home):
    home = Path(make_home([job("j1", "a", DIGEST), job("j2", "b", DIGEST + " 2.")], audit=[("j1", 1, 10, 1)]))
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in home.rglob("*") if p.is_file()}
    for p in home.rglob("*"):
        if p.is_file():
            os.chmod(p, 0o444)
    report.run(home, "report", now=NOW)
    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in home.rglob("*") if p.is_file()}
    assert before == after
