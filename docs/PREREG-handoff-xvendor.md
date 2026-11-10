# Pre-registration: cross-vendor handoff, repo-only vs Scholion records, 2026-11-10

Written and committed before any paid trial of this comparison. Anything added after seeing results
is labelled exploratory. Run on one Windows host with Harbor and Docker, driven by
`uv run python -m oe.xvendor` (`tools/oe/xvendor.py`).

- **Question:** agent A (one vendor's model) worked on a tallyho task, was interrupted, and handed
  over; successor B (the other vendor's model) finishes it. Does B do better when Scholion carries
  A's context (**records**) than when it gets only A's working tree (**repo-only**)? A third
  channel, **notes** (A's `NOTES.md`), runs only from budget left over after the first two.
- **Directions, never pooled:** `sonnet-to-flash` (A on Claude Sonnet 5.5, B on DeepSeek Flash)
  and `flash-to-sonnet` (A on DeepSeek Flash, B on Claude Sonnet 5.5). Every table and claim is per
  direction.
- **Primary metrics (per direction and channel):** B's solved rate (hidden tests pass; Wilson 95%),
  B's cost per solved task (all B spend in the cell over solved sessions), and B's median turns
  (Claude Code `num_turns`).
- **Secondary:** paired task-stratified bootstrap (seed 1, 2000 resamples) of records/repo-only − 1
  for cost and turns, as `site/data/handoff.json` computes it; billed tokens; tool calls; wall time;
  per A, `fix_lines_in_a`.

## Predecessor A

- **Agent:** `oe_agents.handoff_a:HandoffA`, the interrupt family's A (Claude Code on Scholion
  `release/0.0.2`, the tracker's `av` arm, asked to keep `NOTES.md` as it goes;
  `docs/PREREG-handoff-interrupt.md`) with one addition, the **wrap-up**.
- **Why a wrap-up:** in Scholion 0.0.2 an agent writes its records when the av Stop hook asks,
  after its work: in all 12 of the 2026-11-04 tracker `av` sessions (DeepSeek Flash) the Stop
  hook's feedback came first (after agent step 4 to 13); in 10 the first `av record` call is the
  step right after it, and in the other 2 the trajectory shows no `av record` call although their
  records exist (wording corrected in Amendment 1). A cut by `--max-turns`
  ends the session with no Stop, so a hard-cut A would leave Scholion its intent and nothing else;
  the records channel would carry no reasoning by construction. Cross-vendor handoffs in practice
  happen when a person ends one tool's session to switch to another. So after the cut, A's session
  is resumed once (`claude --continue`, inside the same av task, hooks on) with this message and at
  most **4** more turns:

  > Stop here: your session is ending now, and another engineer, possibly using a different tool,
  > will take over this task from your working tree. Do not change any code. Leave what they need
  > to continue, then stop.

  It names no channel: `NOTES.md` (from the instruction) and the av records (from the Stop hook)
  get the same chance. A hard-cut A is not measured here.
- **Cut:** `--ak max_turns=4`, both directions. The interrupt family's 6 was set from cold-run
  medians, but the `av` sessions solved `summarize-abbrev` in 4-5 agent steps, and A must not have
  solved the task when it hands over.
- **Models:** `anthropic/claude-sonnet-5-5` through the Anthropic API (haiku, small-fast and
  subagent aliases at Claude Code's defaults), and `anthropic/deepseek-flash` through
  `https://api.deepseek.com/anthropic` (those aliases set to `deepseek-flash`). Claude Code
  **2.1.322** (npm latest on 2026-11-10) for every A and B.
- **Tasks:** the six of the interrupt family: `compound-discounts`, `csv-escaping`,
  `paginated-scan`, `summarize-abbrev` (`tallyho-cold`), `order-price-snapshot`,
  `config-literal-values` (`tallyho-more`). One A per task per direction (`-k 1`).
- **Freeze and validity:** `oe freeze` into `datasets/_shared/handoff/xv-sonnet/` (A on Sonnet)
  and `.../xv-flash/` (A on Flash). The interrupt family's validity rules hold unchanged (NOTES.md
  present, a file changed, Scholion records, a trajectory, a valid av session, no trial exception,
  hidden tests not yet passing). A Scholion record count of 1 (the intent alone) is valid: it is
  what the records channel then carries, and it is reported. `a.json` also records the wrap-up's
  turns and the code files it changed (`wrapup_changed_files`); B starts from the tree after the
  wrap-up. An invalid A is re-run once at the same cut; if that is invalid too the task is dropped
  from that direction and the drop reported. The leak check (`tools/gen/handoff.py`), `-a nop`
  (every reward 0) and `-a oracle` (every reward 1) must pass on both generated datasets before any
  B runs. The agent running this experiment reads every frozen `NOTES.md` and `records.json` for a
  leak the markers miss and scans every frozen file for either API key; the frozen A's are
  committed before the first B trial.

## Successor B

- **Agents:** repo-only and notes: `claude-code` as shipped. records: `oe_agents.handoff_b:HandoffBAv`,
  the tracker's `av` arm with A's task state put into its av task before Claude starts: the
  workspace gets `/app`'s `.git` and A's patch (it must then equal `/app` byte for byte, and
  `git diff` shows A's work as in every channel), A's records except its intent are posted to the
  task as `agent-a`'s, the task is checkpointed, and `/handoff` is deleted, so B reaches the records
  only through av's SessionStart pack (800 tokens) and pre-read hook. The instruction is the
  interrupt family's two-sentence lead, the channel's sentence, and the goal.
- **Settings:** `--ak max_turns=40`, Claude Code 2.1.322; Sonnet legs also
  `--ak max_budget_usd=0.75` (Claude Code's own stop).
- **Datasets:** `datasets/handoff-xv-sonnet` and `datasets/handoff-xv-flash` at the commit that adds
  the frozen A's.
- **Attempts:** one Harbor job per trial, in rounds: each round runs every (task, channel) once.
  Rounds = ceil(30 / valid tasks) (5 with six tasks: 30 sessions per cell). Primary channels
  (repo-only, records) run all their rounds first, interleaved; notes runs afterwards, in rounds,
  only while the budget lasts.

## Budget and stopping rules

- **Caps:** Claude (every Sonnet A and B): **$20.00**. DeepSeek (every Flash A and B): **$1.00**,
  shared account. Each vendor's jobs live under their own root (`D:\oex\claude`, `D:\oex\deepseek`).
- **Gate, before every launch:** the vendor's priced spend so far (`oe budget`'s pricing: Claude
  Code's reported cost for Sonnet, `tools/oe/prices.toml` peak rates for DeepSeek), plus one
  per-trial ceiling for every job without a result (in flight or killed), plus one more ceiling,
  must not exceed the cap. Ceilings per Claude Code run: Sonnet $0.80, DeepSeek $0.05; an A is two
  runs (cut and wrap-up), so an A batch reserves two ceilings per task. DeepSeek $0.05 (a 40-turn worst case at peak
  rates is about $0.04). A job without a result is charged its ceiling and never re-run. Any
  trial with no price at all stops all launches until explained. No balance endpoint is queried.
- **Re-runs:** a trial whose agent never started (setup failure, including Claude Code's installer
  failing its checksum check) is re-run once and is not a result. Nothing else is re-run.
- **Sessions counted:** every B session whose agent ran (status ok, or Claude Code exiting at its
  turn or budget cap, which counts as unsolved). A records session that is invalid by the
  tracker's av rules (`docs/PREREG-tracker-av.md`) is reported and not counted.
- **Short of 30:** if the gate stops a cell below 30 sessions, or tasks are dropped, that cell is
  reported as descriptive (counts only).
- **Harness stops:** if a trial shows the harness itself broken (an A or B session invalid by the
  rules above for a harness reason, a key reaching the wrong endpoint), launches stop, the defect is
  fixed in a commit that says so, and the broken trials stay in the data, labelled. Outcomes
  (solved or not, cost, turns) are never a reason to stop, change or re-run.

## Analysis and decisions

- Per direction, one table: channel, n, solved, solved rate, cost per solved task (with its
  `cost_source`), median turns. Wilson intervals for solved rate.
- Records is called cheaper (or dearer) than repo-only, or faster in turns, only when the cell has at
  least 30 counted sessions and the 95% interval of the paired delta excludes 0; otherwise the
  difference is reported as descriptive. With six tasks and one A per task, any claim is about these
  tasks and these A's, not handoffs in general.
- If solved rate is at the ceiling in every channel of a direction (the 2026-11-04 tracker accepted
  every session), the solved-rate comparison is reported as uninformative and cost and turns carry
  the result.
- Known differences between channels besides the artifact: the records B runs Claude Code with the
  av hooks and a pack (code map, live work), which repo-only B does not. That is the product as a
  successor would use it; the channel is "Scholion handoff", not "records text alone".

## No-cost validation done before this commit (2026-11-10)

- `uv run pytest -q`: 130 passed (new tests for the wrap-up, the records channel, `adopt`, the
  driver's key isolation, round order and budget gate).
- On a fixture frozen A (a fake A with an `attempt` and a `decision` record, never committed),
  `-a nop` scored 0 and `-a oracle` 1 on all three generated channel tasks.
- Records-channel dry run with `HandoffBAv` against a dead endpoint (`ANTHROPIC_BASE_URL` =
  `127.0.0.1:9`, no key, so no model call was possible): `adopt` posted the 2 records, the
  daemon's changed list was A's one file (no `.git`), `git diff` in the workspace showed it, the
  SessionStart pack (719/800 tokens) listed both records under "Decisions & dead ends", and the av
  session was valid by the tracker's rules.

## Amendment 1 (2026-11-10, before any paid trial)

From a review of the committed design; no trial of this comparison had run.

- **If the wrap-up leaves only the intent.** The design does not change. Every frozen A's record
  count is reported per task, and a records cell whose A's left nothing beyond the intent on most
  tasks is described as "Scholion handoff without A's records" (B still has av's pack and hooks).
- **Secondary metric added: agent steps before the first av Stop-hook feedback** (all agent steps
  when there is none), per channel. The av Stop hook asks B in the records channel to record its
  changes after it has solved the task, which repo-only and notes B are never asked; turns and cost
  include that, this metric does not. Computed from each trajectory (`oe.xvendor report`).
- **Counted sessions, precisely:** a B session counts when Claude Code answered (its stream-json
  result event exists, so turns are known) and the av session is not invalid. A session whose agent
  was started but whose Claude Code never answered (for example `adopt` or the daemon failing, which
  only the records channel can do) is not counted and is reported; two such sessions in a row stop
  all launches (a harness stop).
- **Setup failures cost $0** in the gate (no model call was made) instead of counting as unpriced,
  and their one re-run is queued in the same invocation.
- **Environment:** every variable whose name starts with `ANTHROPIC_`, `CLAUDE` or `DEEPSEEK_`, and
  `AWS_BEARER_TOKEN_BEDROCK`, is removed before a leg's own endpoint and key are set.
- **Order:** the first paid trial is one DeepSeek A on one task (`compound-discounts`), to check
  the wrap-up on a real session (the session resumed, the Stop hook fired, the records, the session
  files and token counts) before the other A's. It is that task's one A if valid, as for any A.
- Claude Code version for every leg: 2.1.322, written to the driver's version file by hand.
