# Results schema oe/1

A run is one file `runs/<run-id>.jsonl`. Line 1 is the run record (`run.schema.json`); every
other line is one session (`session.schema.json`). `oe validate` checks both schemas and these
extra rules:

- The file name is the run id.
- Every session's `run_id` is the run's id, and `(task, arm, attempt)` is unique.
- Only an `ok` session can be `accepted`.
- A run with `dataset.visibility: private` has no session lines, only the run with its `aggregate`.
- A ledger run (`harness.runner: scholion-cloud`, written by `oe import-reports`; see
  `docs/PREREG-ledger.md`) is named `<week>-ledger-<repo>[.<revision>]`, its week a Monday (the
  run's `date` and `ledger.from`); its dataset is `scholion-dev`, public; it carries the `ledger`
  object, whose `repo` is the one in its name and whose `features_merged` is its number of
  sessions; every session is a merged feature (`ok`, `accepted`), its `arm` `teams` or
  `autopilot`, its `task` a slug (lowercase words joined by hyphens, never a title), its cost
  `measured` with a `cost_usd`, and its `interventions` counted. Only a ledger run has `ledger`.

Field notes:

| Field | Meaning |
|---|---|
| `agent.version` | the CLI's own `--version` (e.g. `2.1.316`); the tracker's x-axis labels |
| `config.arm` | the arm, or `multi` when sessions carry several (`session.arm`) |
| `harness.runner` | `harbor`, `scholion-bench` for imported historical runs, or `scholion-cloud` for a ledger week (not an evaluation; never a tracker series) |
| `ledger` | a ledger run's week: the Scholion Cloud daemon's report summary for one repo (merged features, cost, spend, reverts, interventions, medians, runner outcomes, memory signal), plus the owner-to-arm table used and the models seen |
| `interventions`, `unpriced_tokens` | ledger sessions: board decisions and escalations on the feature in the week; tokens with no price, which `cost_usd` leaves out |
| `flags` | written by `oe detect`: `degraded`, `tool_calls_up`, `recovered`, `low_n`, plus `budget_stopped` |
| `status` | `ok` counts; `invalid` (e.g. the Scholion hooks never fired), `error` (harness exception) and `skipped` (budget) never do |
| `cost_source` | `measured` by the CLI, `estimated` from tokens and a price table, `capped` (hit the session cap; charged the cap), `unavailable` |
| `tokens_billed` | input + cache writes + output, cache reads excluded (scholion's convention) |
| `llm_calls` | agent steps in the ATIF trajectory; `turns` is Claude Code's own `num_turns` when known |
| `repeated_dead_ends` | edit calls whose new text matches a task's known wrong approach |
| `trajectory.path` | relative to the jobs directory archived as a GitHub Actions artifact |
