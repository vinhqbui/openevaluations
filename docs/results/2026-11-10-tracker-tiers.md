# tallyho easy and hard tiers: Claude Code on DeepSeek Flash vs Pro, 2026-11-10 (pilot)

Pre-registered in `docs/PREREG-tracker-tiers.md` (with its amendments). Descriptive only: every
cell has fewer than 30 valid sessions, so this claims no significance and no difference between
the models. The hard tier is a **pilot**: the $1.75 cap allowed 2 trials per task on Pro and 3
on Flash.

- **Agent:** Claude Code 2.1.318 (pinned), `max_turns=40`, through
  `https://api.deepseek.com/anthropic`. The haiku, small-fast and subagent aliases are set to the
  arm's own model.
- **Models:** `deepseek-flash` (DeepSeek-V4.1-Flash-1017) and `deepseek-v4-pro`
  (DeepSeek-V4-Pro-0813).
- **Harness:** Harbor 0.25.0, Docker on Windows, `-r 0`.
- **Costs:** `cost_source: estimated`, re-priced from `tools/oe/prices.toml` at DeepSeek's
  **peak** list rates, so they are upper bounds. Most trials ran off-peak, which DeepSeek bills at
  half.

Reproduce the tables:
`uv run oe tiers --prereg docs/PREREG-tracker-tiers.md --also runs/2026-11-04-tallyho-cold-claude-code-cold-5febae.jsonl`.

## Easy tier (`tallyho-cold`, `tallyho-more`)

| arm | n | solved | solved rate [Wilson 95%] | cost per solved | median turns |
|---|---|---|---|---|---|
| Claude Code on DeepSeek Flash | 14 | 13 | 93% [69%, 99%] | $0.0115 | 14.5 |
| Claude Code on DeepSeek Pro | 6 | 4 | 67% [30%, 90%] | $0.1044 | 18.5 |

By dataset:

| arm | dataset | n | solved |
|---|---|---|---|
| Flash | `tallyho-cold` | 12 | 12 |
| Flash | `tallyho-more` | 2 | 1 |
| Pro | `tallyho-cold` | 4 | 3 |
| Pro | `tallyho-more` | 2 | 1 |

- **Flash `tallyho-cold`:** the published run `2026-11-04-…-5febae` (12 sessions, the same
  Claude Code version), reused, not re-run.
- **Pro's misses:**
  - `compound-discounts`: the amounts were right, but the per-discount list was not kept in the
    order given, which the spec asks for.
  - `order-price-snapshot`: 37 turns, hidden tests failed.
- **Flash's miss:** `order-price-snapshot`, 16 turns.
- **Errors:** 1, not in n. Flash's first `order-price-snapshot` trial failed in setup, before
  Claude Code started: its installer rejected the download checksum. It used no tokens and was
  re-run once, per amendment 1.

## Hard tier (`tallyho-hard`, pilot)

| arm | n | solved | solved rate [Wilson 95%] | cost per solved | median turns |
|---|---|---|---|---|---|
| Claude Code on DeepSeek Flash | 12 | 12 | 100% [76%, 100%] | $0.0167 | 24 |
| Claude Code on DeepSeek Pro | 8 | 8 | 100% [68%, 100%] | $0.0998 | 29 |

- **Per task:** 3 trials each on Flash and 2 each on Pro.
- **Errors:** 1, not in n. Pro's first `refund-orders` trial failed the same way, in setup with
  no tokens, and was re-run once.
- **Pro's third pass did not run:** the guard's worst-case reserve of 4 × $0.23 would have taken
  spend past the cap.
- **Cost per solved task, bootstrap 95% interval:** Flash $0.014–0.019, Pro $0.079–0.121.
- **Median wall time per session:** Flash 50 s, Pro 187 s.

## What this shows, and what it does not

- **The hard tier does not separate the models.** Both arms solved every hard trial. Under the
  PREREG's decision rule, the tier is too easy and needs harder tasks before any further spend.
  Pro used more turns (median 29 against 24) and cost about 6× as much per solved task, at these
  list prices.
- **The hard tier is harder than the easy one by effort, not by outcome.** Flash's median turns
  went from 14.5 (easy) to 24 (hard), and cost per solved task from $0.0115 to $0.0167.
- **On the easy tier, Pro solved fewer than Flash** (4/6 against 13/14). The cells are small and
  the intervals overlap widely. This is an observation for a pre-registered follow-up, not a
  finding.

## Spend

$1.4472 of the $1.75 cap, by the harness's accounting (`oe budget`, peak list prices):

| cell | spend |
|---|---|
| hard on Pro | $0.7982 |
| hard on Flash | $0.2007 |
| easy on Pro | $0.4176 |
| easy on Flash (`tallyho-more` only) | $0.0307 |

Two interrupted jobs were set aside and not imported:

- a power loss at about 04:29 UTC;
- a planned host restart at about 13:00 UTC.

Their trials were all still installing Node, so no model was called. They spent $0.

## What a full run would cost

These figures use the mean cost per valid session observed here.

- **Bar for a claim** (30 valid sessions per cell): about $3.00 for hard on Pro, $0.50 for hard on
  Flash, $2.10 for easy on Pro and $0.32 for easy on Flash. That is about $5.90 at peak prices.
- **The planned 3 trials per task:** Pro's hard cell needs 4 more trials, about $0.40, and Pro's
  easy `tallyho-cold` cell needs 8 more, about $0.51.

## Notes

- **Erratum to the PREREG:** it says the reused run `5febae` ran in GitHub Actions on Linux. Its
  run record says `machine: local, os: windows`, Harbor 0.25.0, openevaluations `3366e65`. The
  other differences it lists are unchanged.
- On this host, Docker Desktop's BuildKit could not run `RUN` steps on 2026-11-10. Every image
  here was built with the classic builder (`DOCKER_BUILDKIT=0 COMPOSE_BAKE=false`).
- Run files:
  - `runs/2026-11-10-tallyho-hard-claude-code-cold-e9c518.jsonl` (hard, Pro)
  - `runs/2026-11-10-tallyho-hard-claude-code-cold-ebc5d4.jsonl` (hard, Flash)
  - `runs/2026-11-10-tallyho-cold-claude-code-cold-67816f.jsonl` (easy, Pro)
  - `runs/2026-11-10-tallyho-more-claude-code-cold-31a084.jsonl` (easy, Pro)
  - `runs/2026-11-10-tallyho-more-claude-code-cold-1a1c5d.jsonl` (easy, Flash)
