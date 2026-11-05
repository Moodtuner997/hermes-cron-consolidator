# cron-consolidator

**A read-only plan for tidying a crowded Hermes cron list.**

Cron lists grow one job at a time: a digest for Monday, another for Wednesday, the same pull-request chase for three
repositories, five jobs that all fire at 09:00. `cron-consolidator` reads a profile's cron data and tells you which jobs
look like one job written several times, which ones fire in the same minute, which keep failing and which deliveries
were never confirmed. It changes nothing: you read the plan and decide.

```text
> /cron-consolidator
# Cron consolidation plan

14 enabled job(s) of 14; 14 with token data in the last 14 days. Merging every candidate below would leave **9**.
Read-only: nothing was changed.

## Merge candidates (3)

1. Keep `stale-prs-api` (0 9 * * *) and fold in 2 job(s):
   - `stale-prs-web` (0 9 * * *): prompt ~97% like stale-prs-api; same skills (github) and destination (slack)
   - `stale-prs-docs` (0 9 * * *): prompt ~97% like stale-prs-api; same skills (github) and destination (slack)
   Skills to carry over: github
   Up to 4,464 prompt tokens/day (ceiling: the merged prompt is longer, output tokens not counted).

## Clock-time jobs that fire in the same minute (1)
- at 09:00: `stale-prs-api`, `stale-prs-web`, `stale-prs-docs`, `rates`, `standup-notes`

## Failing jobs (1)
- `rates`: 5 failures in a row; last error: HTTP 502 from the exchange-rate API
```

(The example is a synthetic profile built by `tests/make_demo_profile.py`.)

## What it does

- **Finds jobs that are really one job.** Three signals, all deterministic, no model call: prompts that are
  near-duplicates (`difflib`, 85 % or more after numbers and whitespace are normalised), jobs that share the same
  skills and the same delivery target, and jobs that run the same script. Each candidate says why it was flagged and
  which job to keep (the one that fired most, then the oldest).
- **Counts tokens from what really happened.** The saving comes from `usage_audit.jsonl`, over the last 14 days by
  default. It is a ceiling on prompt-side tokens, because a merged prompt is longer and the output still has to be
  produced; when there is no usage data for a candidate it says so and claims nothing.
- **Finds clock collisions.** Jobs with a fixed time that can fire in the same minute (days of week, month and day of
  month are taken into account: Monday 09:00 and Tuesday 09:00 do not collide). Pollers such as `*/30` are left out,
  otherwise they would chain every job into one group.
- **Lists what needs a look.** Jobs on a failure streak (three or more) and deliveries that were accepted but never
  confirmed (`last_delivery_unverified`).
- **Says what it could not read.** Schedules it cannot parse are listed instead of guessed.

It never applies anything. There is no `--apply`: a merge changes what an agent does, so it stays your decision.

## Install

```bash
hermes plugins install cron-consolidator
hermes plugins enable cron-consolidator
```

## Use

In a session: `/cron-consolidator` (or `/cron-consolidator report --json`). From a shell:

```bash
hermes cron-consolidator report                       # current profile
hermes cron-consolidator report --profile work        # another profile under the same Hermes root
hermes cron-consolidator report --json --days 30      # machine-readable, longer usage window
hermes cron-consolidator report --home /path/to/copy  # a copied HERMES_HOME, for a dry look
```

## Disclosure

- **Network:** none.
- **Reads outside the plugin's own data:** `cron/jobs.json` (including prompts), `cron/usage_audit.jsonl` and
  `cron/executions.db` of the chosen profile, the last one opened read-only. `--profile` reads another profile's cron
  folder under the same Hermes root.
- **Writes:** none. The plugin creates no file and no table; a test checks that the profile is byte-identical after a run.
- **What the report contains:** job names, ids, schedules, skills, delivery targets, and the first 160 characters of a
  failing job's last error. Prompt text is compared but never printed.
- **Shell commands, background processes, credentials:** none. It registers no hook, no tool and no middleware, only
  a slash command and a CLI command.
- **Telemetry:** none.

## How it differs from existing entries

`fleet-policy` reports cost per cron, `hermes-cron` diagnoses a job's health, `custodian` repairs failing jobs and
`cron-bulletin` is an inbox. `cron-consolidator` answers a different question: which jobs should become one. It plans
consolidation, it does not price, diagnose or repair. They compose.

## What real data looked like

On a snapshot of a real deployment (three profiles, 42 enabled jobs, mostly scripts rather than prompts) it found no near-duplicate
prompt, one genuine merge (the same hook-check script scheduled twice, once for late October and once for early
November) and two groups of jobs sharing a minute, six jobs in all. A list of mostly distinct jobs gets a short plan: the
tool reports what is there and does not invent savings.

## Development

```bash
python -m pytest tests -q                         # 29 tests, no Hermes needed
hermes plugins validate .                         # the catalog gate
python tests/make_demo_profile.py /tmp/demo       # a synthetic profile, then: hermes cron-consolidator report --home /tmp/demo
```
