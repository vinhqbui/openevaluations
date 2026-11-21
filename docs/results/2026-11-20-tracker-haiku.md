# Tracker on Claude Haiku 5.5: first run of the series, 2026-11-20

Pre-registered in `docs/PREREG-tracker-av.md` (amendment of 2026-11-20, committed at 19:22 UTC;
the first paid trial started at 19:24 UTC). Descriptive only: every cell has 12 sessions, below
the 30 the decision rule needs. This claims no significance, no difference between the arms and no
ranking of the CLIs. The rows are a new series and are not comparable with the DeepSeek Flash rows
of 2026-11-04 and 2026-11-10.

- **Dataset:** `tallyho-cold` (4 tasks), 3 attempts per task, 12 sessions per leg.
- **Model:** `claude-haiku-5-5` through Anthropic's API, for every leg.
- **Harness:** Harbor 0.25.0, Docker on Windows, started by hand (not GitHub Actions) as
  `tracker.yml` runs it (`-k 3 -n 4 -r 1`), from `0542c11`. The legs ran one at a time between
  19:38 and 20:43 UTC: cold, av, OpenCode, goose.
- **Costs:** each CLI's own figure (`cost_source: measured`).

The figures below are those of `site/data/tracker.json`, built from `runs/2026-11-20-*.jsonl` by
`uv run oe site`.

## Rows

| leg | CLI | solved | Wilson 95% | cost of the leg | cost per solved [95%] | median tokens billed | median LLM calls | median tool calls |
|---|---|---|---|---|---|---|---|---|
| `claude-code-cold` | Claude Code 2.1.329 | 12/12 | [76%, 100%] | $0.0540 | $0.0045 [$0.0038, $0.0052] | 14,684 | 6.5 | 7 |
| `claude-code-av` | Claude Code 2.1.329 on Scholion `release/0.0.2` | 12/12 | [76%, 100%] | $0.0679 | $0.0057 [$0.0050, $0.0063] | 17,312.5 | 10 | 9 |
| `opencode-cold` | OpenCode 1.19.6 | 12/12 | [76%, 100%] | $0.0391 | $0.0033 [$0.0027, $0.0039] | 10,811.5 | 6.5 | 7.5 |
| `goose-cold` | goose v1.60.2 | 12/12 | [76%, 100%] | $0.0634 | $0.0053 [$0.0045, $0.0060] | 17,495.5 | 11 | 10 |

All 12 av sessions were valid under the pre-registered rule. No leg was retried and no trial
failed before spending.

## av against cold on Claude Code

Paired by task, task-stratified bootstrap (seed 1, 2000 resamples), av / cold − 1:

| metric | delta | 95% interval |
|---|---|---|
| cost | +31% | [+21%, +44%] |
| billed tokens | +23% | [+3%, +49%] |
| turns | +26% | [+16%, +38%] |

With 12 sessions per arm this is descriptive, and no claim is made. A claim needs 30 valid
sessions per arm, pooled over weeks with the same model, Claude Code minor version and Scholion
release.

## What the pre-registration asked this report to record

- **Third CLI.** goose v1.60.2 installed from its GitHub release, ran on the Anthropic key and
  reported tokens and cost. The fallbacks (`cline`, `mini-swe-agent`) were not tried.
- **Thinking and effort.** No thinking or effort setting was passed to any CLI. At their
  defaults all of them reasoned: Claude Code's sessions (both legs) report thinking tokens,
  OpenCode's report reasoning tokens, and goose's trajectories contain reasoning text (goose
  reports no separate count). No effort level appears in the job configurations or the
  trajectories, so the level each CLI used is not recorded.
- **Spend.** Four smoke trials, one per leg on `compound-discounts`, not imported: $0.0225. The
  four legs: $0.2245. Total $0.2470 of the $2.00 cap. Twelve times the smoke costs came to $0.27,
  under the $1.80 limit for starting the legs, and every leg stayed under its $0.45 cap.
- **Install checks for goose.** Four jobs of one trial each made no model call and cost nothing.
  Harbor's `version` alone does not pin goose: its installer installs the `stable` tag unless
  `GOOSE_VERSION` is set. The first job ran without `GOOSE_VERSION`. Two ran with it set to
  `v1.60.2`, as the smoke trial and the leg then did. One, after the legs, ran with an invalid
  value, and its install failed.

## Changed between the run and its publication

- **OpenCode's token columns.** Harbor's OpenCode adapter leaves cache writes out of input and
  reasoning tokens out of output. The importer was fixed to add them back, and this leg was
  imported again from the saved job before it was published (`500a76c`). Only its token columns
  changed. Its cost is OpenCode's own figure and did not change.
- **The site.** A tracker series now includes the model and the harness, with one table per
  model, so these rows cannot be read as a continuation of the DeepSeek Flash rows.

## Note added after seeing the results (exploratory)

Added on 2026-11-21. It is not part of the pre-registered analysis.

In the av leg every session was stopped once by Scholion's Stop hook, after the agent had written
its final answer, and asked to record what it had changed. The first `av record` of every session
was then refused because its summary was longer than the limit, which that release's hook text
does not state, so the agent tried again. The pre-registration says this step counts, and it is
counted in the row above.

Scholion has been called Margincode since 2026-11-12. On its main branch it now asks for the
record before the final answer and no longer refuses a long summary
([margincode-dev/open-margincode#93](https://github.com/margincode-dev/open-margincode/pull/93)).
No release has that change. The tracker pins a release, so this row changes only when the pin
does, and nothing here says what a later release will measure.
