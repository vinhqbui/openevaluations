# Pre-registration: the ledger (Scholion Cloud's own backlog, weekly), 2026-11-05

This covers every ledger run (`harness.runner: "scholion-cloud"`, `runs/<week>-ledger-<repo>.jsonl`)
from the first week the foundry merges work until this file changes. It is written before any
ledger data exists. Anything added after seeing a week is labelled exploratory.

## What the ledger is, and what it is not

Scholion Cloud (the foundry, agentvcs Plan 15) works the backlog of its own repositories:
`scholion`, `agentvcs` and `openevaluations`. Agents build, personas review, and a human approves
every merge on the board. The ledger records that work as it happened, one run per repository
per week.

It is **not an evaluation**. There is no control arm, the tasks are whatever the backlog held that
week, the same team chose and wrote them, and a week has **2 to 10 merged features**. Two weeks
differ in their tasks as much as in anything else. **No claim is made from the ledger**: not that
Scholion helps, not that one path beats the other, not that a trend is real. It has no
significance tests, intervals or deltas, and it is never a tracker series. A comparison of the
loop against a plain-git arm on the same backlog is the separate, owner-gated E5-lite evaluation,
with its own pre-registration.

## What is reported

Per repository and week (Monday 00:00 UTC to the next Monday), from the Scholion Cloud daemon's
`GET /v1/ee/reports?repo=R&from=<Monday>&to=<Sunday>` (agentvcs
`ee/scholion-ee-daemon/src/reports.rs`), imported with `oe import-reports`:

- **Merged features.** A feature is a task merged in the week (`tasks.status = 'merged'`,
  `merged_at` in it). Each one is a session: `task` its slug, `arm` its path, `accepted` true.
- **Cost per merged feature** (primary). A feature's cost is every `ee.priced_usage` row on its
  task, whoever made it (the builder's and its reviewers'), whenever: `cost_usd`,
  `cost_source: "measured"`. The page divides the week's feature costs by its features, overall
  and per path. Personas on the Teams path run on a subscription; their tokens are priced at the
  connection's list prices, which is what `priced_usage` holds, not what was paid. Tokens with no
  price are left out of the cost and counted (`unpriced_tokens`); such a feature is marked on the
  page.
- **Interventions per feature** (primary). The daemon's interventions in the week (board
  decisions `gate.approve`, `gate.request_changes`, `gate.merge`, and runner escalations) that
  fall on the week's merged features, divided by them. In the foundry every merge is a board
  decision by a human, so about one per feature is expected. Interventions on tasks that did not
  merge that week, and those on a feature before the week began, are not in this ratio; the
  week's total is the run's `ledger.human_interventions`.
- **Secondary, as the daemon reports them:** backlog-to-merge time per feature (`wall_secs`) and
  its median, reverts in the week, escalations, gate decisions, review latency and gate wait
  medians, mean review rounds, the runner's job outcomes, and the memory signal (records written,
  pack tokens and items, `known:` findings).

## Paths (the arm)

- **teams**: the director's agents (Claude Code) in Scholion task workspaces, persona review,
  a human on the board.
- **autopilot**: the Scholion Cloud runner (DeepSeek, BYOK) taking small items on its own,
  persona review, a human on the board.

The export carries no path, so it is derived from the task's owner, the persona that took it:
`fable-opus` and `fable-sonnet` are teams, `builder` and `reviewer` are autopilot (the foundry
runbook's personas). An owner not in that table is refused until `oe import-reports --arm
OWNER=teams|autopilot` names it, and the mapping used is written into the run (`ledger.owners`).

## How a reverted feature counts

- A week's run is imported once, after the week ends, and never edited (`runs/` is append-only).
- A feature merged in week 1 and reverted later stays in week 1 as it was published. The revert
  is counted in the week it happened (`ledger.reverts`).
- A reverted task goes back to open. When it merges again it is a feature of that later week,
  with `attempt` = 1 + its earlier reverts, and its cost is the task's whole cost so far, the
  first round's included. That first round is then counted in both weeks; this is deliberate: a
  revert's cost shows up in what the feature finally cost.
- If an export must be replaced (a wrong price, a wrong period), the week is superseded with
  `oe import-reports --revision 2 --notes WHY`; the site shows a week's highest revision and the
  old file stays.

## Other counting rules

- A merged task that did not come from the backlog has no backlog-to-merge time; its `wall_secs`
  is task-to-merge and its `reason` says so. It is a feature like any other.
- Every repository's sessions are published by slug only. Titles, targets, task ids, actors and
  board comments are never copied. Slugs are made from titles (Scholion's `slugify`), so a slug
  can show words of a private (agentvcs) title; that is accepted.
- An empty week is a run with no sessions.

## Decision rule

None. The ledger is reported, never tested. Below 30 sessions per cell no significance claim is
made anywhere on openevaluations, and a ledger cell is a week with 2 to 10.
