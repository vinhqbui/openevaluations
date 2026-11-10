# Cross-vendor handoff (Sonnet 5.5 ↔ DeepSeek Flash), 2026-11-10: stopped after the predecessors

Pre-registered in `docs/PREREG-handoff-xvendor.md` (with Amendments 1 to 3). **No successor (B)
session ran.** Every result below is about the predecessors (A), the sessions that are interrupted
and hand over. Both directions fell below Amendment 3's floor of four valid A's, so by that rule no
B was launched until the director sees this table. Nothing here is a finding about handoffs, about
Scholion, or about either model's quality.

- **Agent:** Claude Code 2.1.322 (pinned) on the Scholion arm (`oe_agents.handoff_a:HandoffA`,
  Scholion `release/0.0.2`), cut by Claude Code's own `--max-turns 6`, then resumed once
  (`--continue`, same session) with the wrap-up message and at most 4 turns.
- **Models:** `claude-sonnet-5-5` through the Anthropic API; `deepseek-flash` through
  `https://api.deepseek.com/anthropic`. Each leg's environment carries only its own key and endpoint
  (`tools/oe/xvendor.py` `leg_env`); a scan of every job and frozen file found neither key.
- **Harness:** Harbor, Docker on Windows, `-k 1 -n 1 -r 0`, one task per job.
- **Tasks:** the interrupt family's six (`tallyho-cold`: compound-discounts, csv-escaping,
  paginated-scan, summarize-abbrev; `tallyho-more`: order-price-snapshot, config-literal-values).

## Result: no valid predecessor in either direction

| direction | A on | A trials (first + re-run) | valid A's | B sessions run |
|---|---|---|---|---|
| `sonnet-to-flash` | Sonnet 5.5 | 12 | 0 | 0 |
| `flash-to-sonnet` | DeepSeek Flash | 12 (+1 pilot) | 1, which then failed the leak check | 0 |

**The per-direction B tables the PREREG names (channel, n, solved, solved rate, cost per solved
task, median turns) are empty: n = 0 in every cell.** No successor session ran, so nothing here
compares repo-only with records.

### A on Sonnet 5.5 (`sonnet-to-flash`)

Turn counts in brackets are Claude Code's `num_turns`; `--max-turns 6` reports 7 when it cuts.
Costs are what Claude Code reported (`cost_source` reported). After `--continue` the wrap-up's
total covers the whole session.

| task | attempt | cut ended | code files changed at cut | hidden tests at cut | wrap-up | records beyond intent | oe freeze | cost (USD) |
|---|---|---|---|---|---|---|---|---|
| compound-discounts | first | success (7) | 2 | pass | success (2) | 1 | invalid: solved at the cut | $0.0790 |
| csv-escaping | first | error_max_turns (7) | 2 | pass | success (1) | 1 | invalid: solved at the cut | $0.0637 |
| paginated-scan | first | error_max_turns (7) | 2 | pass | success (2) | 1 | invalid: solved at the cut | $0.0860 |
| summarize-abbrev | first | success (13) | 2 | pass | success (2) | 1 | invalid: solved at the cut | $0.0926 |
| compound-discounts | re-run | success (7) | 2 | pass | success (2) | 1 | invalid: solved at the cut | $0.0786 |
| csv-escaping | re-run | error_max_turns (7) | 2 | pass | success (3) | 1 | invalid: solved at the cut | $0.0735 |
| paginated-scan | re-run | error_max_turns (7) | 2 | pass | success (2) | 1 | invalid: solved at the cut | $0.0785 |
| summarize-abbrev | re-run | error_max_turns (7) | 2 | pass | success (2) | 1 | invalid: solved at the cut | $0.0906 |
| config-literal-values | first | error_max_turns (7) | 2 | pass | success (1) | 2 | invalid: solved at the cut | $0.0815 |
| order-price-snapshot | first | error_max_turns (7) | 3 | pass | success (2) | 1 | invalid: solved at the cut | $0.0863 |
| config-literal-values | re-run | error_max_turns (7) | 1 | pass | success (1) | 2 | invalid: solved at the cut | $0.0803 |
| order-price-snapshot | re-run | error_max_turns (7) | 3 | pass | success (4) | 2 | invalid: solved at the cut | $0.0926 |

Sonnet fixed every task inside the 6-turn cut, in both attempts: 12 of 12 A's passed the hidden
tests before they were cut. That held even though the instruction asks the agent to keep
`NOTES.md` as it goes. In three of the twelve A's, Claude Code finished (`success`) before reaching
the cap. Every task is dropped from this direction, as the PREREG's one-re-run rule requires.

### A on DeepSeek Flash (`flash-to-sonnet`)

Costs were re-priced from `tools/oe/prices.toml` at peak rates (`cost_source` estimated), so they
are upper bounds.

| task | attempt | cut ended | code files changed at cut | hidden tests at cut | wrap-up | records beyond intent | oe freeze | cost (USD) |
|---|---|---|---|---|---|---|---|---|
| compound-discounts | first | error_max_turns (7) | 1 | pass | error_max_turns (5) | 0 | invalid: solved at the cut | $0.0161 |
| csv-escaping | first | error_max_turns (7) | 2 | pass | error_max_turns (5) | 3 | invalid: solved at the cut | $0.0101 |
| paginated-scan | first | error_max_turns (7) | 2 | pass | error_max_turns (5) | 0 | invalid: solved at the cut | $0.0141 |
| summarize-abbrev | first | error_max_turns (7) | 1 | pass | error_max_turns (5) | 1 | invalid: solved at the cut | $0.0199 |
| compound-discounts | pilot (cut 4) | error_max_turns (5) | 0 | fail | success (2) | 0 | pilot, not an A | $0.0116 |
| compound-discounts | re-run | error_max_turns (7) | 1 | pass | error_max_turns (5) | 0 | invalid: solved at the cut | $0.0138 |
| csv-escaping | re-run | error_max_turns (7) | 1 | pass | error_max_turns (5) | 4 | invalid: solved at the cut | $0.0092 |
| paginated-scan | re-run | error_max_turns (7) | 1 | pass | error_max_turns (5) | 0 | invalid: solved at the cut | $0.0143 |
| summarize-abbrev | re-run | error_max_turns (7) | 2 | pass | error_max_turns (5) | 0 | invalid: solved at the cut | $0.0164 |
| config-literal-values | first | error_max_turns (7) | 2 | fail | error_max_turns (5) | 0 | valid | $0.0164 |
| order-price-snapshot | first | error_max_turns (7) | 0 | fail | success (2) | 0 | invalid: no code changed | $0.0142 |
| order-price-snapshot | re-run | error_max_turns (7) | 0 | fail | success (2) | 0 | invalid: no code changed | $0.0137 |

- **Four tasks were solved at the cut twice** (compound-discounts, csv-escaping, paginated-scan,
  summarize-abbrev) and are dropped.
- **order-price-snapshot changed no code at the cut, twice**, and is dropped. Flash spent its six
  turns reading the code and writing `NOTES.md`.
- **config-literal-values is the one valid A.** Its code and `NOTES.md` were in place, and its own
  new test failed on a case-sensitivity detail. **`tools/gen/handoff.py`'s leak check then failed
  on it.** Hidden-test markers (the test name `test_percent_signs_are_literal`,
  `assert cfg.shop_name == "Half % Off"`, `with pytest.raises(ConfigError):`) appear in A's
  `workspace.patch` and trace.
  - **The match looks coincidental.** A wrote its own test with a different helper and different
    values, under the name and assertion the task's wording suggests. Its trajectory never touches
    `/tests` or the hidden file, and the image does not contain them.
  - **The A is still not used.** The PREREG requires the leak check to pass before any B runs.
  - **The A is kept, not committed.** It sits outside the repo
    (`D:\oex\frozen\xv-flash\config-literal-values__MpLGmmK\`), so `datasets/_shared/handoff/`
    gains no xv family and the generator's `--check` stays green.
- **The cut-4 pilot** (Amendment 2) changed no code. With the cut at 4, every A would have been
  invalid. At 6, most A's had already solved the task. On these tasks there is no cut value that
  leaves Flash's work half done.

## What was seen that matters for a re-design (exploratory)

- **Easy tasks have no "half done" window.**
  - On the six interrupt-family tasks, Sonnet's first one to three edits already make the whole fix.
  - Flash goes from "only read the code" (cut 4) to "fixed" (cut 6) on four of six tasks.
  - Choosing another cut value would be tuning with nothing to aim at.
- **The 4-turn wrap-up is too short for Flash to record.**
  - Every Flash wrap-up that followed code changes hit its cap (`error_max_turns`, 5).
  - These wrap-ups first updated `NOTES.md`, then got the av Stop hook's request for records, and
    were cut while answering it.
  - 6 of the 9 that changed code left nothing beyond the intent.
  - Sonnet wrap-ups ended on their own in 1 to 4 turns, with 1 or 2 records each.
  - So a Flash A's records channel would mostly carry the intent alone.
- **Harder tasks exist:** `datasets/tallyho-hard` (4 tasks), currently only on the unmerged
  `tracker-tiers` branch.
  - In that run (no `NOTES.md` instruction, no av hooks), Claude Code on Flash solved 12 of 12
    sessions in a median of 24 turns (18 to 35), at an estimated $0.0167 per solved session.
  - Its code edits spread from about the 5th to the 15th agent step of 10 to 19, so a cut near the
    middle would plausibly leave the work half done.
  - That is an observation from another experiment, not a tested cut.

## Spend

- **Claude:** **$0.9832** of the $20.00 cap. This is the sum of Claude Code's reported cost for the
  12 Sonnet A's. The gate's own figure is $1.2468: the four first-attempt `tallyho-cold` A's ran
  before the cumulative-cost fix (Amendment 3), so their `result.json` counts the cut twice. No
  Claude B ran.
- **DeepSeek:** **$0.1698** of the $1.00 cap (estimated at peak rates), including the $0.0116
  pilot.
- **Gate:** nothing was unpriced and no job was left without a result. No balance endpoint was
  queried.

## Caveats

- **What these numbers cover:** one A per task per attempt, six easy tasks, one host. They say
  something about this cut on these tasks, not about either model in general.
- **The agent setup:** Claude Code 2.1.322, Scholion 0.0.2's av hooks, and the `NOTES.md`
  instruction were the same for both models. The models were not compared under any other agent
  setup.
- **Not imported into `runs/`:** the A trials are predecessors, not sessions of the comparison. The
  interrupt family does not import A's either; its frozen A's are the record. Their trajectories
  stay under `D:\oex\claude` and `D:\oex\deepseek`, outside the repo.
