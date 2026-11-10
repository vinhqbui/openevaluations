# tallyho-hard: validation record

Checked on 2026-11-10, before any paid trial, with Harbor 0.25.0 and Docker 29.9.2 (Docker
Desktop on Windows). No model was called.

## Harbor: nop scores 0, oracle scores 1

```text
$ uv run harbor run -p datasets/tallyho-hard -a nop -n 1 -o D:/oej/tiers-validate --job-name hard-nop-3
$ uv run oe rewards D:/oej/tiers-validate/hard-nop-3 --expect 0
4/4 trial(s) scored 0
$ uv run harbor run -p datasets/tallyho-hard -a oracle -n 2 -o D:/oej/tiers-validate --job-name hard-oracle
$ uv run oe rewards D:/oej/tiers-validate/hard-oracle --expect 1
4/4 trial(s) scored 1
```

On this host Docker Desktop's BuildKit could not run any `RUN` step that day ("error running
prestart hook #0: signal: segmentation fault"), even for a two-line busybox Dockerfile. The
images were built with the classic builder (`DOCKER_BUILDKIT=0 COMPOSE_BAKE=false`). The
Dockerfile is the one every tallyho task uses, so the builder does not change the image.

## pytest: the hidden test fails on the base and passes with the fix

`tools/tests/test_tasks.py::test_hidden_test_fails_on_the_base_and_passes_with_the_fix` runs this
for every task in `tasks/`, `tasks-more/` and `tasks-hard/`. It applies `base_overlay` first, so
`export-tax-drift` is checked against its seeded tree. It also checks that the fix touches exactly
`relevant_files`.

## The obvious fixes fail

Each variant below was applied to the oracle (or to the base, for `export-tax-drift`), and the
whole suite was run with the hidden test added.

| Task | Obvious fix | Hidden tests failed |
|---|---|---|
| `refund-orders` | re-quote the order on the refund date and post the reverse of that quote | 3 of 13: coupon expired since payment, coupon book changed, refund through another `Workflow` |
| `refund-orders` | re-quote on `order.placed_on` | 3 of 13: pay date is not the placing date, coupon book changed, another `Workflow` |
| `export-tax-drift` | copy the table in `load_config`, keep the cached `default_tax_table` | 2 of 6: changing a default `Config()`'s rates, changing a `default_tax_table()` result |
| `store-paging-refactor` | `MemoryStore._records` returns the stored dicts without copying | 1 of 23: callers may change the records they get back |
| `line-tax-allocation` | round each line's discount share on its own | 1 of 46: left-over cents go to the largest remainders |
| `line-tax-allocation` | floor each share, drop the left-over cents | 3 of 46 |

## What each task tests

- `refund-orders` (a feature across `models.py`, `workflow.py` and `ledger.py`): the refund
  reverses exactly what the sale recorded, not a fresh quote.
- `export-tax-drift` (a cause far from its symptom): the image's `default_tax_table` is wrapped in
  `functools.lru_cache` (seeded from `base/export-tax-drift/`). Every `Config` and every default
  quote therefore shares one mutable rates dict, and `load_config` writes into it. The symptom
  shows up in configs, quotes and the CSV export; the cause is in `pricing/tax.py`.
- `store-paging-refactor` (a refactor that must keep behaviour): paging moves into
  `RecordStore`. The hidden test pins the old paging behaviour of both backends: cursors that are
  not ids, limits of 0 and below, exactly full last pages, empty collections, and copies of
  returned records. The golden cases pass on the unmodified base too, which shows they describe the
  old behaviour.
- `line-tax-allocation` (a spec whose edge case the obvious fix misses): largest-remainder
  allocation of the discount, then per-line half-even tax. An independent `Fraction` reference in
  the test checks 40 seeded random orders against the spec.

The base tree still contains the six easy-tier bugs. The hard tests avoid them: they use single
percentage coupons, orders under one page, and customer names without commas.
