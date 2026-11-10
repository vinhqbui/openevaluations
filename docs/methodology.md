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

The weekly schedule is off for now (2026-11-05); runs are started by hand.

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

Predecessor A runs once per task and is frozen; each channel is a generated single-step Harbor
task built from that same frozen A, so only the channel differs. Families: relay (curated A, 10
tasks, so far only Scholion's own runs) and interrupt (a real A cut at a pre-registered turn count;
`docs/PREREG-handoff-interrupt.md`).

- **Tasks.** The four `tallyho-cold` tasks and the two of `tallyho-more`, a separate set on the
  same base tree, so the weekly tracker's task set never changes. `tools/tests/test_tasks.py`
  checks every task: its hidden test fails on the base tree, and with its fix the whole suite
  passes.
- **A.** `oe_agents.handoff_a:HandoffA` is the tracker's `av` arm with a request to keep
  `NOTES.md`, cut by Claude Code's `--max-turns`. Afterwards `/app` is tarred, and
  `oe freeze <job> --cut-turns N` writes `datasets/_shared/handoff/interrupt/<task>/`:
  `workspace.patch` (A's tree against the base, `NOTES.md` excluded), `NOTES.md`,
  `trajectory.json`, `records.json` and `a.json` (who A was, where it stopped, validity, sha256 of
  the rest). Frozen files are never edited; the generator checks the hashes.
- **Channels.** `tools/gen/handoff.py` writes `datasets/handoff-interrupt/<task>--<channel>/`.
  Every image is the base tree as one commit with A's patch applied, uncommitted. repo-only adds
  nothing; trace adds `/handoff/trace.md` (the trajectory rendered, messages and outputs cut at 4000 characters,
  A's tool calls in full); notes adds `/app/NOTES.md`. The instruction is a fixed two-sentence lead,
  the channel's one sentence saying where its artifact is, and the task's goal. The records
  channel (A's Scholion records loaded into B's daemon) is not generated until `ClaudeCodeAv` can
  seed them.
- **Leak check.** Markers: the hidden test's file stem, its test function names and its lines of 20
  or more characters, and the fix's added lines of 20 or more characters, all minus anything
  already in the base tree. A hidden-test marker in any artifact stops generation. A fix line
  stops it for a curated (relay) A; in a real A, whose image never held the fix, it is A's own
  progress and is counted as `fix_lines_in_a` in task.toml.
- **Validation.** `-a nop` scores 0 (A had not already solved the task) and `-a oracle`, which
  resets A's work and applies the fix, scores 1 on every generated task (`oe rewards`).
- **Import.** `oe import-harbor <jobs...> --channels --merge` makes one run per successor:
  `<task>--<channel>` becomes task and arm, so `/handoff` pairs channels against repo-only by task.
- **Cross-vendor family** (`docs/PREREG-handoff-xvendor.md`). A on one vendor's model, B on the
  other's, both Claude Code: `xv-sonnet` (A on Sonnet 5.5) and `xv-flash` (A on DeepSeek Flash).
  A is cut at 4 turns, then its session is resumed once with a fixed wrap-up message (at most 4
  turns, `handoff_a.py --ak wrapup_turns=4`), so the av Stop hook gets its chance to ask for
  records, as when a person ends a session to switch tools. Channels: repo-only, records and notes.
  The records channel's B is `oe_agents.handoff_b:HandoffBAv`: the `av` arm with A's patch and
  `.git` put into its task's workspace and A's records (but its intent) posted to the task as
  `agent-a`'s before Claude starts; `/handoff` is then deleted, so the records reach B only through
  av's pack and hooks. `python -m oe.xvendor` runs it: one Harbor job per trial in rounds, each
  vendor's spend gated before every launch against its own cap.
