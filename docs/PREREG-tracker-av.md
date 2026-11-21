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

## Amendment 2026-11-20: a new series on Claude Haiku 5.5 (before any paid trial)

Written and committed at about 19:22 UTC on 2026-11-20, before any paid trial of this series.
The owner decided on 2026-11-20 that no more DeepSeek money is spent and every paid run goes
through the Anthropic API key. Everything above still holds except where this section says
otherwise.

- **New series, not comparable.** From this run on, the tracker runs on `claude-haiku-5-5`
  (Anthropic's first-party API) instead of DeepSeek Flash. These rows are a new series. They are
  never pooled with, compared with or plotted as a continuation of the DeepSeek Flash rows. The
  site keys each series by dataset, agent and model, so they get their own charts. A pool for
  the decision rule above also needs the same model.
- **Model:** `claude-haiku-5-5`, Anthropic first-party API. `ANTHROPIC_API_KEY` is the
  Anthropic key. `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` are unset, and no DeepSeek
  endpoint or key is used. Prices are from `tools/oe/prices.toml` (checked 2026-11-10, prompts up
  to 100k tokens): $0.10 input, $0.125 5-minute cache write, $0.01 cache read and $0.50 output per
  million tokens. Thinking and effort stay at each CLI's default, and the report records what the
  default was.
- **Legs** (`datasets/tallyho-cold` at `3aa0520`, 4 tasks, all included; `-k 3 -n 4 -r 1`,
  `--agent-setup-timeout-multiplier 2`):
  - `claude-code-cold`: `claude-code`, `-m anthropic/claude-haiku-5-5`, `--ak max_turns=40`. The
    `ANTHROPIC_DEFAULT_HAIKU_MODEL`, `ANTHROPIC_SMALL_FAST_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL`
    aliases are set to `claude-haiku-5-5`. Without them Claude Code's own default small model
    could be a different, differently priced Claude model, and every call in a session must go
    to one model.
  - `claude-code-av`: `oe_agents.claude_code_av:ClaudeCodeAv`, the same flags and aliases, plus
    `--ak av_version=release/0.0.2`. The pinned tarball downloaded fresh and matched its sha256 on
    2026-11-20.
  - `opencode-cold`: `opencode`, `-m anthropic/claude-haiku-5-5`, its own defaults.
  - **third CLI:** `goose` (Block's goose, Harbor's `goose` agent), `-m
    anthropic/claude-haiku-5-5`, `--ak max_turns=40`. It installs from goose's GitHub release
    with no account, takes an Anthropic key, and reports tokens and cost. Fallbacks, in order, if
    goose cannot run on the key or reports no tokens: `cline`, then `mini-swe-agent`, with the
    same model and their defaults. The report names the CLI used and why the others were not.
  - **Codex is dropped for this series.** Codex CLI speaks only OpenAI's Responses API, so it
    cannot run on an Anthropic key.
- **CLI versions**, read once at 19:17 UTC before the first leg and pinned with `--ak version=`:
  Claude Code `2.1.329` (npm, both Claude Code legs), OpenCode `1.19.6` (npm `opencode-ai`),
  goose `v1.60.2` (its latest GitHub release; goose is not on npm). Harbor `0.25.0`.
- **Smoke trials.** Before each leg, one trial of `compound-discounts`, one attempt (`-k 1 -n 1
  -r 0`), in its own job. Smoke trials are not imported as runs. Their spend counts toward the
  budget and is reported.
- **Budget:** $2.00 hard cap for everything in this series run, smoke trials included. After the
  smoke trials, the four legs' cost is extrapolated (12 × each leg's smoke cost). If that sum
  passes $1.80, no full leg runs. Each full leg is capped at $0.45 with `oe budget <job> --cap
  0.45`. The legs run one at a time: cold, then av on the same UTC day, then OpenCode, then goose.
  Cost is the CLI's own figure where it reports one (`cost_source` measured) and is otherwise
  priced from `prices.toml` (estimated).
- **Failures:** a trial that fails before the agent spends anything (zero tokens) is an
  infrastructure failure, not a session, and its leg may be retried once in a new job. A leg
  that fails after spending is reported and not rerun.
- **What is compared:**
  - `av` vs `cold` on Claude Code, on the same day: the paired deltas above (`vs_cold`). With 12
    sessions per arm this is descriptive. No claim is made.
  - Across CLIs (Claude Code, OpenCode, goose) the rows are a tracker. They report solved rate,
    cost, tokens, turns, tool calls and wall time per leg, with no significance claim and no
    ranking (n = 12 < 30 per cell).
  - Nothing is compared with the DeepSeek Flash rows of 2026-11-04 or 2026-11-10. They may be
    shown side by side in the report, labelled as a different model.
