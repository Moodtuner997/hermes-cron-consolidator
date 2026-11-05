from pathlib import Path

from cron_consolidator import analysis

from conftest import NOW, job

DIGEST = "Summarise the unread newsletters in my inbox, keep only what concerns my projects, and send a digest."


def run(home, days=14):
    return analysis.analyze(Path(home) / "cron", days=days, now=NOW)


def test_near_duplicate_prompts_become_one_candidate(make_home):
    home = make_home([
        job("j1", "digest-mon", DIGEST + " Week 1.", "0 8 * * mon"),
        job("j2", "digest-tue", DIGEST + " Week 2.", "0 8 * * tue"),
        job("j3", "backup-check", "Verify that last night's backup finished and report the size.", "0 7 * * *"),
    ])
    res = run(home)
    assert len(res["merge_candidates"]) == 1
    cand = res["merge_candidates"][0]
    assert {cand["keep"]["id"], cand["fold_in"][0]["id"]} == {"j1", "j2"}
    assert res["after_merge"] == 2


def test_two_jobs_running_the_same_script_are_a_candidate(make_home):
    home = make_home([
        job("j1", "hook-check-a", "", "0 9 * * *", script="/srv/hermes/scripts/hook-check.py", no_agent=True),
        job("j2", "hook-check-b", "", "0 15 * * *", script="/srv/hermes/scripts/hook-check.py", no_agent=True),
        job("j3", "other", "", "0 12 * * *", script="/srv/hermes/scripts/other.py", no_agent=True),
    ])
    cand = run(home)["merge_candidates"]
    assert len(cand) == 1 and "runs the same script (hook-check.py)" in cand[0]["fold_in"][0]["why"]


def test_unrelated_prompts_are_left_alone(make_home):
    home = make_home([
        job("j1", "a", "Check the weather in Lyon every morning and tell me if I need an umbrella."),
        job("j2", "b", "Review open pull requests on the main repository and list the stale ones."),
    ])
    assert run(home)["merge_candidates"] == []


def test_same_skills_and_destination_group_even_with_different_prompts(make_home):
    home = make_home([
        job("j1", "a", "Look at the finance mailbox for invoices.", skills=["gmail", "sheets"], deliver="slack"),
        job("j2", "b", "Chase unpaid invoices older than thirty days.", skills=["sheets", "gmail"], deliver="slack"),
        job("j3", "c", "Draft the monthly accounts summary for the board.", skills=["sheets", "gmail"], deliver="email"),
    ])
    cands = run(home)["merge_candidates"]
    assert len(cands) == 1
    ids = {cands[0]["keep"]["id"], *(f["id"] for f in cands[0]["fold_in"])}
    assert ids == {"j1", "j2"}  # j3 has the same skills but another destination


def test_same_minute_collision_only_when_schedules_really_overlap(make_home):
    home = make_home([
        job("j1", "a", "First unrelated task about weather forecasts for the week.", "0 9 * * *"),
        job("j2", "b", "Second unrelated task about repository hygiene and stale branches.", "0 9 * * mon"),
        job("j3", "c", "Third unrelated task about reading the news in three languages.", "0 9 * * tue"),
        job("j4", "d", "Fourth unrelated task about the quarterly accounting export.", "1 9 * * *"),
    ])
    col = run(home)["slot_collisions"]
    assert len(col) == 1 and {j["id"] for j in col[0]["jobs"]} == {"j1", "j2", "j3"}
    assert col[0]["slot"] == "09:00"


def test_savings_come_from_observed_prompt_tokens_only(make_home):
    home = make_home(
        [job("j1", "a", DIGEST + " One.", "0 8 * * mon"), job("j2", "b", DIGEST + " Two.", "0 8 * * tue")],
        audit=[("j1", 1, 2000, 300), ("j1", 8, 2000, 300), ("j2", 2, 1400, 200),
               ("j2", 30, 9999, 9999)],  # outside the 14-day window: ignored
    )
    cand = run(home)["merge_candidates"][0]
    assert cand["keep"]["id"] == "j1"  # most fires in the window
    assert cand["saving"]["prompt_tokens_per_day_ceiling"] == 100  # 1400 tokens / 14 days


def test_no_audit_data_means_no_saving_is_claimed(make_home):
    home = make_home([job("j1", "a", DIGEST + " One."), job("j2", "b", DIGEST + " Two.", "5 8 * * *")])
    assert run(home)["merge_candidates"][0]["saving"] is None


def test_failures_and_unverified_deliveries(make_home):
    home = make_home([
        job("j1", "flaky", "Fetch the exchange rates and post them to the finance channel.", failure_streak=4,
            last_error="HTTP 502"),
        job("j2", "fine", "Remind me to stretch every two hours during working time.", failure_streak=2),
        job("j3", "mute", "Send the evening summary of the day to my phone number.",
            last_delivery_unverified=["telegram:123"]),
    ])
    res = run(home)
    assert [f["id"] for f in res["failing"]] == ["j1"] and res["failing"][0]["error"] == "HTTP 502"
    assert [u["id"] for u in res["unverified_delivery"]] == ["j3"]


def test_disabled_jobs_are_ignored_and_bad_rows_survive(make_home):
    home = make_home([
        job("j1", "a", DIGEST + " One."),
        job("j2", "b", DIGEST + " Two.", enabled=False),
        "not a job", {"no": "id"},
        job("j3", "odd", "A task whose schedule this plugin cannot read at all.", "@reboot"),
    ])
    res = run(home)
    assert res["merge_candidates"] == [] and res["jobs"]["total"] == 3 and res["jobs"]["enabled"] == 2
    assert [u["id"] for u in res["untimed"]] == ["j3"]


def test_pollers_do_not_chain_unrelated_jobs_into_one_group(make_home):
    home = make_home([
        job("j1", "poller", "Poll the status page every half hour and tell me about outages.", "*/30 * * * *"),
        job("j2", "morning", "Prepare the morning briefing from the calendar and the inbox.", "0 9 * * *"),
        job("j3", "evening", "Prepare the evening shutdown checklist for the build servers.", "0 18 * * *"),
        job("j4", "nine-too", "Refresh the sales leads sheet from the CRM export file.", "0 9 * * *"),
    ])
    col = run(home)["slot_collisions"]
    assert len(col) == 1 and {j["id"] for j in col[0]["jobs"]} == {"j2", "j4"} and col[0]["slots"] == ["09:00"]


def test_interval_jobs_are_not_collisions(make_home):
    home = make_home([
        {**job("j1", "a", "Poll the status page every half hour and tell me about outages."),
         "schedule": {"kind": "interval", "minutes": 30}},
        job("j2", "b", "Check the build server disk usage and warn me above eighty percent."),
    ])
    assert run(home)["slot_collisions"] == []


def test_utf8_bom_is_accepted(make_home, tmp_path):
    home = make_home([job("j1", "a", "Anything long enough to be a real prompt for the test.")])
    p = Path(home) / "cron" / "jobs.json"
    p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
    assert run(home)["jobs"]["total"] == 1
