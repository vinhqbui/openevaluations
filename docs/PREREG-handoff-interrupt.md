# Pre-registration: handoff-interrupt, channels vs repo-only, 2026-11-02

Written before any predecessor or successor run. It covers the first run of each stage of
`.github/workflows/handoff.yml` (or the same commands run locally). Anything added after seeing
results is labelled exploratory.

- **Question:** agent A worked on a tallyho task and was cut off. For a successor B starting from
  that same frozen A, what does each channel change against **repo-only** (A's working tree and
  nothing else)? Channels: **trace** (A's full transcript at `/handoff/trace.md`), **notes**
  (A's `NOTES.md` at the repository root) and, once built, **records** (A's Scholion records).
- **Primary metrics:** acceptance by the hidden tests per channel (Wilson 95%); per-session cost
  and turns as paired deltas against repo-only.
- **Secondary metrics:** billed tokens, tool calls, LLM calls, wall time, cost per accepted task,
  and per task `fix_lines_in_a` (lines of the reference fix that A had already written, from the
  leak check). No dead ends are defined for these tasks, so `repeated_dead_ends` is not reported.

## Predecessor A

- **Agent:** `oe_agents.handoff_a:HandoffA`: Claude Code on the Scholion framework, exactly the
  tracker's `av` arm (`docs/PREREG-tracker-av.md`: hooks, daemon, jj workspace, Scholion
  `release/0.0.2`), plus one paragraph appended to the instruction asking it to keep `NOTES.md` as
  it goes (`agents/oe_agents/handoff_settings.py`). A runs on Scholion so that one A leaves all four
  channels; every channel is built from that same run.
- **Model:** `anthropic/deepseek-flash` through `https://api.deepseek.com/anthropic`, with the
  haiku, small-fast and subagent aliases set to `deepseek-flash`. Claude Code is the npm latest when
  A runs, recorded in each `a.json`.
- **Tasks:** six, all included: the four `tallyho-cold` tasks and the two `tallyho-more` tasks
  (`order-price-snapshot`, `config-literal-values`). The two were written on 2026-11-02, after this
  file's first version and before any run, on the same base tree; each hidden test fails on the
  base tree and passes with its fix (`tools/tests/test_tasks.py`). They are not in the weekly
  tracker's set, so `docs/PREREG-tracker-av.md` is unchanged.
- **Cut:** `--ak max_turns=6`. The 2026-11-02 cold run took 8 to 21 turns per accepted session
  (median 13), so six turns is short of the fastest finish: A has usually read the code and may have
  started an edit.
- **Attempts:** one A per task (`-k 1`), frozen by `oe freeze` into
  `datasets/_shared/handoff/interrupt/<task>/` and never replaced afterwards.
- **Validity of an A (decided now):** an A is invalid when any of these hold, as `oe freeze` checks:
  no or an empty `NOTES.md`; no file changed besides `NOTES.md`; no Scholion records; no
  trajectory; its av session is invalid by the tracker's rules; its trial raised; or it already
  passed the hidden tests when cut. The generated tasks must then pass the leak check (no marker of
  the hidden test in any artifact), score 0 with `-a nop` and 1 with `-a oracle`. An invalid A is
  re-run once at the same cut; if that is invalid too, the task is dropped and the drop reported.
  No A is re-run for any other reason, in particular not for notes or a trace that look poor.
- **Review:** a person reads each frozen A's `NOTES.md` and trace before merging the freeze PR,
  only to check for a leak the markers miss. A leak found that way drops the task; nothing else
  does.

## Successor B

- **Agents:** `claude-code` as shipped, with `--ak max_turns=40` and the Claude Code version A ran
  with (`--ak version=`), on `anthropic/deepseek-flash` as above. Second successor: `opencode` on
  `deepseek/deepseek-flash`, reported separately and never pooled with Claude Code.
- **Dataset and revision:** `datasets/handoff-interrupt` at the commit that merges the freeze PR:
  6 tasks × 3 channels (repo-only, trace, notes), fewer if a task is dropped under the validity rule.
- **Attempts:** `-k 8` per (task, channel) per successor, so 48 sessions per channel cell (40 with
  one task dropped, 32 with two).
- **Budget:** `$10` per stage, a sixth per (successor, channel) job; `oe budget` re-prices Claude
  Code's DeepSeek figures from `tools/oe/prices.toml`. Expected well under `$1` for the successor
  stage (about $0.005 a session).
- **Records channel:** not run here. It needs B's Scholion daemon to start from A's records, which
  `ClaudeCodeAv` cannot do yet. When it can, an amendment to this file comes first, and the records
  cell uses the same frozen A's.

## Analysis and decisions

- **Analysis:** per successor, Wilson intervals for acceptance per channel; paired task-stratified
  bootstrap (seed 1, 2000 resamples) of channel/repo-only − 1 for cost, turns and tokens
  (`vs_repo_only` in `site/data/handoff.json`), truncated sessions skipped.
- **Decision rule:** a cell needs at least 30 valid sessions for any claim; below that, counts
  only. A channel is reported as cheaper (or dearer) than repo-only only when the 95% interval of its
  paired cost delta excludes 0, and the same for turns. With six tasks, a claim is about these six
  tasks and these A's; it is not a claim about handoffs in general. If acceptance is at the ceiling in
  every channel, the acceptance comparison is reported as uninformative, as in the tracker.
- **Known overlap between channels:** the trace contains everything A did, including its writes to
  `NOTES.md`, so trace is a superset of notes by construction. That is the channel as defined, not
  a leak.
