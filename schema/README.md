# Results schema oe/1

A run is one file `runs/<run-id>.jsonl`. Line 1 is the run record (`run.schema.json`); every
other line is one session (`session.schema.json`). `oe validate` checks both schemas and these
extra rules:

- The file name is the run id.
- Every session's `run_id` is the run's id, and `(task, arm, attempt)` is unique.
- Only an `ok` session can be `accepted`.
- A run with `dataset.visibility: private` has no session lines, only the run with its `aggregate`.

Field notes:

| Field | Meaning |
|---|---|
| `agent.version` | the CLI's own `--version` (e.g. `2.1.316`); the tracker's x-axis labels |
| `config.arm` | the arm, or `multi` when sessions carry several (`session.arm`) |
| `harness.runner` | `harbor`, or `scholion-bench` for imported historical runs |
| `flags` | written by `oe detect`: `degraded`, `tool_calls_up`, `recovered`, `low_n`, plus `budget_stopped` |
| `status` | `ok` counts; `invalid` (e.g. the Scholion hooks never fired), `error` (harness exception) and `skipped` (budget) never do |
| `cost_source` | `measured` by the CLI, `estimated` from tokens and a price table, `capped` (hit the session cap; charged the cap), `unavailable` |
| `tokens_billed` | input + cache writes + output, cache reads excluded (scholion's convention) |
| `llm_calls` | agent steps in the ATIF trajectory; `turns` is Claude Code's own `num_turns` when known |
| `repeated_dead_ends` | edit calls whose new text matches a task's known wrong approach |
| `trajectory.path` | relative to the jobs directory archived as a GitHub Actions artifact |
