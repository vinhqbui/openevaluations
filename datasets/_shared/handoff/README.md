# Frozen predecessors (handoff benchmark)

One directory per family and task, `<family>/<task>/`, written by `oe freeze` from predecessor A's
Harbor trial and never edited afterwards (`a.json` pins the sha256 of every other file):

| File | What | Channel |
|---|---|---|
| `a.json` | A's agent, model, cut, where it stopped, files changed, validity | - |
| `workspace.patch` | A's working tree against `datasets/_shared/tallyho/src`, `NOTES.md` excluded | every channel |
| `trajectory.json` | A's ATIF trajectory, rendered to `/handoff/trace.md` | trace |
| `NOTES.md` | A's notes, placed at `/app/NOTES.md` | notes |
| `records.json` | A's Scholion records | records (not generated yet) |

`tools/gen/handoff.py` builds `datasets/handoff-<family>/` from these. See
`docs/methodology.md` (Handoff benchmark) and `docs/PREREG-handoff-interrupt.md`.
