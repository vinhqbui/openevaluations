# Pre-registration: tallyho easy and hard tiers, Claude Code on DeepSeek Flash vs Pro, 2026-11-10

Written and committed before the first paid trial. Anything added after seeing results is
labelled exploratory.

- **Question:** for the same Claude Code version, settings and tasks, how do DeepSeek Flash and
  DeepSeek Pro compare on solved rate, cost per solved task and turns, separately on easy tasks
  and on hard ones? The tracker's tasks are easy: Claude Code on Flash solved 12 of 12 sessions in
  every run, so they cannot tell models or agents apart. The hard tier is meant to.
- **Tiers** (`datasets/tiers.toml`; never pooled across tiers):
  - **easy:** `datasets/tallyho-cold` (4 tasks) and `datasets/tallyho-more` (2 tasks), unchanged.
  - **hard:** `datasets/tallyho-hard` (4 tasks: `refund-orders`, `export-tax-drift`,
    `store-paging-refactor`, `line-tax-allocation`). All four are included. It was validated
    before this file was written: nop 0/4, oracle 4/4, hidden tests fail on the base, obvious
    fixes fail (`datasets/_shared/tallyho/tasks-hard/VALIDATION.md`). Dataset at commit `553bc33`.
- **Arms:** one agent, `claude-code` (Harbor's adapter), with two models through DeepSeek's
  Anthropic-compatible endpoint `https://api.deepseek.com/anthropic`:
  - **flash:** `-m anthropic/deepseek-flash` (DeepSeek says it is served by
    DeepSeek-V4.1-Flash-1017).
  - **pro:** `-m anthropic/deepseek-v4-pro` (served by DeepSeek-V4-Pro-0813).
  - Model id, endpoint and prices are from https://api-docs.deepseek.com/quick_start/pricing and
    https://api-docs.deepseek.com/guides/anthropic_api, checked 2026-11-10.
  - Both arms: Claude Code `--ak version=2.1.318` (pinned; the version of the existing easy-tier
    Flash data), `--ak max_turns=40`, and the aliases `ANTHROPIC_DEFAULT_HAIKU_MODEL`,
    `ANTHROPIC_SMALL_FAST_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL` set to the arm's own model
    (`deepseek-flash` or `deepseek-v4-pro`), so every call in a session goes to one model.
  - No effort level or other settings beyond the tracker's. `ANTHROPIC_API_KEY` is unset;
    `ANTHROPIC_AUTH_TOKEN` is the DeepSeek key, passed by name from `$DEEPSEEK_API_KEY`.
  - Harbor 0.25.0, Docker on Windows, `-r 0` (no retries, so no unseen spend), agent timeout
    1800 s on the hard tier and 900 s on the easy tier (each task's `task.toml`).
- **Existing data reused:** easy-tier Flash on `tallyho-cold` is the published run
  `runs/2026-11-04-tallyho-cold-claude-code-cold-5febae.jsonl`. It used the same Claude Code
  version (2.1.318) and `max_turns=40`, but it ran in GitHub Actions on Linux, before this file,
  with `-r 1`, and it does not record which Flash build served it. It is not re-run. No Flash
  data exists for `tallyho-more`; that cell runs only if budget is left (see order).
- **Metrics, all per tier and per arm:**
  - **primary:** solved rate (hidden tests pass; Wilson 95%); cost per solved task (spend over
    valid sessions divided by solved ones, session bootstrap, seed 1); median turns (Claude
    Code's `num_turns`).
  - **secondary:** billed tokens, tool calls, wall time, sessions that errored or timed out.
- **Validity:** a session counts when Harbor reports no exception (`status: ok`). Errors and
  timeouts are reported per cell with their count and are never silently dropped. Their cost
  counts toward the cap and the cell's total spend, but not toward cost per solved task.
- **Costs:** Claude Code prices DeepSeek models at a Claude fallback, so `oe import-harbor` and
  `oe budget` re-price every session's tokens from `tools/oe/prices.toml` (`cost_source:
  estimated`). The rows are DeepSeek's **peak** rates: Flash $0.30 / $0.006 / $1.20 and Pro
  $1.32 / $0.044 / $3.96 per million input / cache-hit / output tokens. DeepSeek bills off-peak
  hours at half, so every cost here is an upper bound on what was billed.
- **Budget:** **$1.75 hard cap** for all paid trials of this comparison, by the harness's own
  accounting (`oe budget`). The same DeepSeek account funds another benchmark. All paid jobs go
  under one root, and before every batch:
  `oe budget <root> --cap 1.75 --reserve <batch trials × worst case per trial>` must exit 0, or the
  batch does not run.
  - The worst case per trial is 1.5 × the highest cost seen in that cell so far. Before a cell's
    first trial it is $0.30 for Pro on hard, $0.10 for Flash on hard and Pro on easy, and $0.03
    for Flash on easy.
  - The DeepSeek balance endpoint is not queried.
- **Order and attempts:** batches of one trial per task (`-k 1`), up to 3 trials per task per
  cell, in this order:
  1. hard-pro, hard-flash, easy-pro (`tallyho-cold`): first trial;
  2. hard-pro, hard-flash: second trial;
  3. hard-pro, hard-flash: third trial;
  4. easy-pro (`tallyho-cold`): second and third trials;
  5. easy-flash and easy-pro on `tallyho-more`, one trial each, if anything is left.

  A batch whose guard fails is skipped and the next one is tried. If any hard cell ends with
  fewer than 3 trials per task, the hard tier is reported as a **pilot**, together with what a
  full run would cost from the observed per-trial means. A full run is 3 trials per task, and also
  30 valid sessions per cell, the bar for any claim.
- **Analysis:** descriptive. Per tier, one table: arm, n, solved, solved rate, cost per solved
  task, median turns, generated from `runs/` with `oe stats` (`stats.summary`). Every cell has
  n < 30, so the report claims no significance and no difference between models. It reports
  counts and intervals.
- **Decision rule:** if the hard tier separates the arms, or leaves both well below the easy
  tier's ceiling, it becomes a candidate tracker dataset, and a full run (30 valid sessions per
  cell) gets its own PREREG and budget. If both arms solve every hard task, the tier is too easy
  and gets harder tasks before any further spend.

## Amendment 2026-11-10 (after the first batch started; one trial result seen)

- The first attempt at batch 1 (hard-pro) was cut off by a host power loss at about 04:29 UTC.
  All four trials were still installing Node in agent setup, so no Claude Code process ran and
  no model was called. That job is set aside, its containers and images are removed, and it is
  not counted as any session. Batch 1 was started again at 12:06 UTC.
- In the rerun, `refund-orders` failed in agent setup: Claude Code's installer refused its
  download ("Staged binary no longer matches the verified checksum"). No tokens were used and
  the agent never started. **Rule from here on:** a trial that fails before Claude Code starts
  (zero tokens, no `claude-code.txt`) is an infrastructure failure, not a session. It is rerun
  once for the same task in a separate job, and both are reported. A failure after Claude Code
  has started is an error session, as above.

## Amendment 2026-11-10, second (planned host restart)

- Planned host restart at about 13:00 UTC. The 2 trials in flight (`tallyho-more`:
  `config-literal-values` and `order-price-snapshot` on Flash, order step 5) were discarded and
  are re-run. No other change.
  - Both were still in agent setup, installing Node. No Claude Code process ran, no tokens were
    used, and `oe budget` counts $0 for them.
  - Their job is set aside and not imported.
- Spend by the harness's accounting before the restart: $1.2518 of the $1.75 cap.
  - The guard skipped three batches because spend plus reserve would pass the cap: hard-pro's
    third trial (reserve $0.93) and easy-pro's second and third trials (reserve $0.61 each).
  - The hard tier is therefore a pilot: Pro has 2 trials per task, Flash has 3.

## Erratum 2026-11-10 (a factual correction; no design change)

"Existing data reused" says run `5febae` ran in GitHub Actions on Linux. Its run record says
`machine: local, os: windows`, Harbor 0.25.0 and openevaluations `3366e65`. Its Claude Code
version (2.1.318) and its 12 sessions are as stated.
