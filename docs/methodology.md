# Methodology

The site's version is `site/methodology/index.html`; this file is the source of truth for the rules.

## Running

- Harbor, one fresh container per trial. History collapsed to one commit. The agent runs as a
  non-root user (`[agent] user = "agent"`). Hidden tests are uploaded to `/tests` only for the
  verifier, which writes `/logs/verifier/reward.txt`.
- Each dataset is validated before use: `-a nop` scores 0 and `-a oracle` scores 1 on every task.
  `tallyho-cold` passed both on 2026-11-02 (Harbor 0.25.0, Docker 29.9 on Windows).
- The tracker does not pin CLI versions; comparisons that need a fixed version pin it with
  `--ak version=...` and say so in their PREREG.

## The weekly tracker

Three legs on DeepSeek Flash, `-k 3` on `tallyho-cold`: Claude Code (`cold`), Claude Code on the
Scholion framework (`av`, `agents/oe_agents/claude_code_av.py`) and OpenCode (`cold`). Both Claude
Code legs install the same Claude Code version, read from npm when the run starts. The `av` arm,
its validity rules and the analysis are pre-registered in `docs/PREREG-tracker-av.md`. An `av`
point on `/tracker` carries `vs_cold`, paired by task against its own run's cold arm, else the
one cold-only run of the same agent and model that day. With no such run, or more than one, the
point stays unpaired.

Claude Code reports DeepSeek sessions at a Claude list-price fallback. `oe import-harbor` and
`oe budget` re-price them from `tools/oe/prices.toml` (`cost_source: estimated`).

## Statistics

- Acceptance: Wilson 95% interval.
- Cost per accepted task: spend over accepted sessions, session bootstrap (2000, seed 1).
- Deltas: paired by task, mean over tasks of arm/control − 1, task-stratified bootstrap (2000,
  seed 1), truncated sessions skipped. `oe stats --paired` reproduces scholion's published
  Haiku numbers exactly (test `test_paired_report_reproduces_the_published_haiku_numbers`).
- No significance claim below 30 valid sessions per cell.

## Change detection (`oe detect`)

Series = (dataset, agent, model, arm). Baseline = the previous four runs of the series.

| Flag | Rule |
|---|---|
| `low_n` | fewer than 12 valid sessions; no other flag |
| `degraded` | Wilson upper bound < baseline acceptance − 0.15 |
| `tool_calls_up` | median tool calls > 1.5 × baseline median |
| `recovered` | previous run flagged, this one inside both thresholds |

## Handoff benchmark (phase P3)

Predecessor A runs once per task and is frozen (workspace, NOTES.md, ATIF trajectory, Scholion
records). Each channel is a generated single-step Harbor task built from the same frozen A, so
only the channel differs. Channels: repo-only, trace, notes, records. Families: relay (curated
A, 10 tasks) and interrupt (real A cut at a pre-registered turn count, 6 tasks). A leak check
keeps hidden tests and fix hunks out of every frozen artifact.
