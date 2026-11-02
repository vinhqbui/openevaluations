# Pre-registration: tallyho-cold, Claude Code cold vs on Scholion (weekly), 2026-11-02

This covers every weekly tracker run from 2026-11-02 until this file changes. Anything added after
seeing results is labelled exploratory.

- **Question:** for the same Claude Code version and model on the same tasks, what does running it
  on the Scholion framework (arm `av`) change against Claude Code as shipped (arm `cold`)?
- **Primary metrics:** per-session cost and turns, as paired deltas `av` vs `cold`. The first
  cold run accepted 12 of 12 sessions, so acceptance is at its ceiling and cannot show a gain.
- **Secondary metrics:** acceptance (Wilson 95%), billed tokens, tool calls, LLM calls, wall time,
  and the av arm's own counts: hooks fired per session, pack size, records written.
- **Agents and exact model ids:** `claude-code` (arm `cold`) and
  `oe_agents.claude_code_av:ClaudeCodeAv` (arm `av`), both with `anthropic/deepseek-flash` through
  `https://api.deepseek.com/anthropic`, `--ak max_turns=40`, and the haiku, small-fast and
  subagent model aliases set to `deepseek-flash`. Claude Code's version is the npm latest when the
  run starts, the same for both legs, and recorded per run (`agent.version`). Scholion is
  `release/0.0.2`, sha256-pinned in `agents/oe_agents/av_settings.py`.
- **What the av arm is:** the setup scholion-bench calls `av` with `--jit-hooks`. A daemon with
  its bundled Postgres starts per trial as the agent user, `/app` is imported as repo `app`, and
  the task starts over HTTP. `/app` becomes the task's jj workspace after a byte-for-byte check
  against the base tree. Claude Code runs with four hooks: SessionStart (an 800-token pack),
  PostToolUse, PreToolUse and Stop, with `AV_HOOK_WAIT_SECS=0`. There is no MCP server and no
  semantic index; packs use full-text search. The workspace has no `.git`, so the agent's
  `git status` fails where it works in the cold arm. That is how Scholion behaves, not a defect
  of the harness. The Stop hook's one nudge to record changes costs a turn, and that turn counts.
- **Validity (decided before any run):** an av session is `invalid`, and never counts, when any
  of these hold:
  - no SessionStart hook fired;
  - its pack was empty;
  - any hook wrote to `hooks.err`;
  - the final checkpoint failed.

  A cold session is invalid only on a harness exception (`error`).
- **Dataset and revision:** `datasets/tallyho-cold` (4 tasks), all included.
- **Attempts:** `-k 3` per task per arm, so 12 sessions per arm per week.
- **Budget:** `$10` per run in total, a third per leg; `oe budget` re-prices Claude Code's
  DeepSeek figures from `tools/oe/prices.toml`. Expected about $0.15 per leg.
- **Analysis:** paired task-stratified bootstrap (seed 1, 2000 resamples) of `av`/`cold` − 1 per
  metric, over the same day's runs (`vs_cold` in `site/data/tracker.json`).
- **Decision rule:** a weekly cell has 12 sessions, so no week alone supports a claim. A claim
  about cost or turns needs at least 30 valid sessions per arm, pooled over consecutive weeks with
  the same Claude Code minor version and Scholion release. That takes three weeks, and the claim
  says which weeks it pools. A change of Scholion release starts a new pool.
