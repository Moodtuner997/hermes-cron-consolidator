import json
import os
from pathlib import Path

import pytest

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


def put_profile(root: Path, name=None) -> Path:
    """A profile folder under ``root`` (``root`` itself for the default one) holding one job."""
    base = root / "profiles" / name if name else root
    (base / "cron").mkdir(parents=True)
    (base / "cron" / "jobs.json").write_text(json.dumps({"jobs": [job("j1", "only", "x" * 40)]}), encoding="utf-8")
    return base


@pytest.mark.parametrize("bad", ["../../elsewhere", "..", ".", "a/b", "a\\b", "Work", "", "-x", "x" * 65, "C:\\temp"])
def test_a_profile_is_a_name_not_a_path(tmp_path, bad):
    root = tmp_path / "root"
    put_profile(root, "work")
    put_profile(tmp_path / "elsewhere")  # a folder outside profiles/ that a ../.. would reach
    for from_chat in (False, True):
        out = report.run(root, ["--profile", bad], from_chat=from_chat)
        assert "takes a profile name" in out and "enabled job(s)" not in out


@pytest.mark.parametrize("good", ["work", "w-1_x", "0", "x" * 64])
def test_ordinary_profile_names_still_work(tmp_path, good):
    root = tmp_path / "root"
    put_profile(root, good)
    assert "1 enabled job(s) of 1" in report.run(root, ["--profile", good], from_chat=True)


def test_home_is_for_the_shell_only(tmp_path):
    root = tmp_path / "root"
    folder = put_profile(root, "work")
    assert "1 enabled job(s) of 1" in report.run(Path("nowhere"), ["--home", str(folder)])  # the shell
    chat = report.run(root, ["--home", str(folder)], from_chat=True)
    assert "available from the shell only" in chat and "enabled job(s)" not in chat
    assert "--home" not in report.run(root, "help", from_chat=True) and "--home" in report.run(root, "help")


def seen_from(tmp_path, out: str) -> bool:
    return str(tmp_path) in out or tmp_path.as_posix() in out


def test_a_chat_is_told_what_went_wrong_but_not_where(tmp_path, monkeypatch):
    root = tmp_path / "root"
    fresh = root / "fresh"
    fresh.mkdir(parents=True)
    broken = put_profile(root, "broken")
    (broken / "cron" / "jobs.json").write_text("{not json", encoding="utf-8")
    denied = put_profile(root, "denied")
    cases = {
        "a profile without jobs.json": (fresh, []),
        "a wrong --profile": (root, ["--profile", "nope"]),
        "a jobs.json that is not JSON": (broken, []),
    }
    for label, (home, args) in cases.items():
        chat, shell = report.run(home, args, from_chat=True), report.run(home, args)
        assert chat.startswith("cron-consolidator: ") and not seen_from(tmp_path, chat), (label, chat)
        assert seen_from(tmp_path, shell), (label, shell)  # the shell keeps the path

    def refuse(cron_dir, **_):
        raise PermissionError(13, "Permission denied", str(cron_dir / "jobs.json"))

    monkeypatch.setattr(report.analysis, "analyze", refuse)
    chat, shell = report.run(denied, "", from_chat=True), report.run(denied, "")
    assert "Permission denied" in chat and not seen_from(tmp_path, chat)
    assert seen_from(tmp_path, shell)


def test_the_json_names_the_profile_folder_for_the_shell_only(make_home):
    home = Path(make_home([job("j1", "a", "x" * 40)]))
    assert json.loads(report.run(home, "--json", now=NOW))["profile_cron_dir"] == str(home / "cron")
    assert "profile_cron_dir" not in json.loads(report.run(home, "--json", now=NOW, from_chat=True))


def test_never_writes_into_the_profile(make_home):
    home = Path(make_home([job("j1", "a", DIGEST), job("j2", "b", DIGEST + " 2.")], audit=[("j1", 1, 10, 1)]))
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in home.rglob("*") if p.is_file()}
    for p in home.rglob("*"):
        if p.is_file():
            os.chmod(p, 0o444)
    report.run(home, "report", now=NOW)
    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in home.rglob("*") if p.is_file()}
    assert before == after
