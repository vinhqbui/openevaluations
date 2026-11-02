# Pre-registration: <dataset> <comparison>, <YYYY-MM-DD>

Write this before any paid run and commit it next to the run files it will produce. Anything
added after seeing results is labelled exploratory. (Adapted from scholion
`bench/results/2026-10-31-relay-image/PREREG.md`.)

- **Question:** the one comparison this run answers, with the arms or channels named.
- **Primary metric:** e.g. tasks accepted by the hidden tests, per arm; or cost per accepted task.
- **Secondary metrics:** turns, LLM calls, tool calls, billed tokens, repeated dead ends.
- **Agents and exact model ids:** e.g. `claude-code` with `anthropic/claude-haiku-5-5`; CLI version
  pinned or not (`--ak version=`).
- **Dataset and revision:** `datasets/<name>` at commit `<sha>`; tasks included or dropped, and why.
- **Attempts:** `-k N` per task per arm; seed if any.
- **Budget:** cap in USD (`oe budget --cap`), per-session cap, and the stop rule.
- **Analysis:** Wilson intervals for acceptance; paired task-stratified bootstrap (seed 1, 2000
  resamples) for deltas against `<control arm>`.
- **Decision rule:** what result changes what we do. With fewer than 30 valid sessions per cell,
  report counts and make no significance claim.
