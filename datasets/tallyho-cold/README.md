# tallyho-cold

Four one-file bugs in tallyho, a 25-file Python shop library written for benchmarking (from
Scholion's `bench/tasks-tallyho`). One agent, cold start, hidden pytest file per task. Generated
by `tools/gen/tallyho.py`; do not edit the task directories by hand.

- `compound-discounts`
- `csv-escaping`
- `paginated-scan`
- `summarize-abbrev`

```bash
uv run harbor run -p datasets/tallyho-cold -a nop      # every reward 0
uv run harbor run -p datasets/tallyho-cold -a oracle   # every reward 1
uv run harbor run -p datasets/tallyho-cold -a claude-code -m anthropic/claude-haiku-5-5 -k 3 -o jobs
```
