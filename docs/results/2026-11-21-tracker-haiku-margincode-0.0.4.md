# Tracker on Claude Haiku 5.5: second run, the av arm on Margincode 0.0.4, 2026-11-21

Pre-registered in `docs/PREREG-tracker-av.md` (amendment of 2026-11-21, pushed at 06:29 UTC as
`64dd370`; the first paid trial started at 06:41 UTC). The amendment says the rows of this run
are published whatever they show. Descriptive only: every cell has 12 sessions, below the 30 the
decision rule needs. This claims no significance, no difference between the arms and no ranking
of the CLIs.

- **Dataset:** `tallyho-cold` (4 tasks), 3 attempts per task, 12 sessions per leg.
- **Model:** `claude-haiku-5-5` through Anthropic's API, for every leg.
- **Harness:** Harbor 0.25.0, Docker on Windows, started by hand (not GitHub Actions) as
  `tracker.yml` runs it (`-k 3 -n 4 -r 1`), from `64dd370`. The legs ran one at a time between
  06:52 and 07:56 UTC: cold, av, OpenCode, goose.
- **CLI versions,** read once at 06:26 UTC: Claude Code 2.1.330 (2.1.329 on 2026-11-20),
  OpenCode 1.19.6, goose v1.60.2.
- **The av arm** runs Margincode `release/0.0.4`, the first release under that name (it was
  Scholion until 2026-11-12). The run of 2026-11-20 used `release/0.0.2`.
- **Costs:** each CLI's own figure (`cost_source: measured`).

The figures below are those of `site/data/tracker.json`, built from `runs/2026-11-21-*.jsonl` by
`uv run oe site`.

## Rows

| leg | CLI | solved | Wilson 95% | cost of the leg | cost per solved [95%] | median tokens billed | median LLM calls | median tool calls |
|---|---|---|---|---|---|---|---|---|
| `claude-code-cold` | Claude Code 2.1.330 | 12/12 | [76%, 100%] | $0.0545 | $0.0045 [$0.0039, $0.0052] | 15,407.5 | 7 | 7 |
| `claude-code-av` | Claude Code 2.1.330 on Margincode `release/0.0.4` | 12/12 | [76%, 100%] | $0.0580 | $0.0048 [$0.0041, $0.0055] | 18,782.5 | 7 | 6 |
| `opencode-cold` | OpenCode 1.19.6 | 12/12 | [76%, 100%] | $0.0450 | $0.0037 [$0.0030, $0.0044] | 13,675.5 | 7 | 8 |
| `goose-cold` | goose v1.60.2 | 12/12 | [76%, 100%] | $0.0614 | $0.0051 [$0.0044, $0.0057] | 18,433 | 10 | 9.5 |

All 12 av sessions were valid under the pre-registered rule. No leg was retried and no trial
failed before spending.

## av against cold on Claude Code

Paired by task, task-stratified bootstrap (seed 1, 2000 resamples), av / cold − 1:

| metric | delta | 95% interval |
|---|---|---|
| cost | +7% | [+1%, +14%] |
| billed tokens | +20% | [+14%, +28%] |
| turns | −10% | [−17%, −0.4%] |

With 12 sessions per arm this is descriptive, and no claim is made. A claim needs 30 valid
sessions per arm, pooled over weeks with the same model, Claude Code minor version and Margincode
release. This run is the first of that pool for release 0.0.4.

## The two runs side by side

Each column is its own day, with its own cold leg. The two differ in the Margincode release and
in the Claude Code version (2.1.329, then 2.1.330). A difference between the columns is not a
tested effect: 12 sessions per arm on each day.

| | 2026-11-20 | 2026-11-21 |
|---|---|---|
| Margincode release of the av arm | 0.0.2 | 0.0.4 |
| cold, cost per solved | $0.0045 | $0.0045 |
| av, cost per solved | $0.0057 | $0.0048 |
| av against cold, cost | +31% [+21%, +44%] | +7% [+1%, +14%] |
| av against cold, billed tokens | +23% [+3%, +49%] | +20% [+14%, +28%] |
| av against cold, turns | +26% [+16%, +38%] | −10% [−17%, −0.4%] |
| median LLM calls, cold and av | 6.5 and 10 | 7 and 7 |
| av sessions the Stop hook stopped | 12 of 12 | 0 of 12 |

## What the av sessions did with the record step

This is what the logs show. It is not part of the pre-registered analysis.

- In all 12 sessions the SessionStart hook printed the pack and, after it, the line that asks for
  the record before the final message.
- In all 12 the agent stored a record before its final message: one decision in each, and a
  note as well in one. Every summary was within the 200-character limit (119 to 181
  characters), so no summary was cut.
- The Stop hook ran once in each session and stopped none of them. On 2026-11-20, with release
  0.0.2, it stopped every session once and the first record of every session was refused.
- No hook wrote an error, and every final checkpoint succeeded.

## What the pre-registration asked this report to record

- **The av smoke session** was valid under the four conditions, so the av leg ran.
- **Spend.** Four smoke trials, one per leg on `compound-discounts`, not imported: $0.0216. The
  four legs: $0.2189. Total $0.2405 of the $2.00 cap. Twelve times the smoke costs came to $0.26,
  under the $1.80 limit for starting the legs, and every leg stayed under its $0.45 cap.
- **Thinking and effort.** No thinking or effort setting was passed to any CLI, as on
  2026-11-20.
- **Checked before the first trial, with no model call.** The arm's install, setup, task start
  and hook commands ran on the release archive in the `compound-discounts` task image, and the
  log directory they left evaluated as valid.

## Changed with this run

- **The page names the release.** An av row on the tracker page now reads "av · Margincode
  0.0.4" or "av · Margincode 0.0.2".
- **Pools per release.** `oe detect` compares an av run only with earlier av runs on the same
  release. This run is the first on 0.0.4 in its series, so it has no baseline and no flag.
- **The empty-pack condition** is judged on the SessionStart output before the first line that
  starts with `av: `, because the release prints lines after the pack. A 0.0.2 log evaluates as
  it did.

## A sentence of the 2026-11-20 report that is now dated

That report ends by saying that no release has the change that asks for the record before the
final answer. That was so on that day. Release 0.0.4, published on 2026-11-21, has it, and the
row above is the first measured with it.
