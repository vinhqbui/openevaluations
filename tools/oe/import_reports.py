"""Imports a Scholion Cloud reports export as the ledger: runs/<week>-ledger-<repo>.jsonl.

The input is the JSON answer of the Scholion Cloud daemon's `GET /v1/ee/reports?repo=R&from=MON&to=SUN`
(agentvcs `ee/scholion-ee-daemon/src/reports.rs`): `repo`, `from`, `to`, an object `summary`,
and the row sections `features`, `interventions`, `reverts`, `runner_outcomes`, ... One export of
one repository for one week (Monday 00:00 UTC to the next Monday) becomes one run:

- `harness.runner: "scholion-cloud"`, `dataset.name: "scholion-dev"` (the live backlog), the
  week's figures from `summary` in the run's `ledger` object.
- One session per merged feature (a `features` row): `task` the task's slug, `arm` its path,
  `accepted` true (a feature is a merged task), `cost_usd` the feature's `cost_usd` (every
  `ee.priced_usage` row on the task) with `cost_source: "measured"`, `wall_secs` backlog to merge,
  `attempt` 1 + the feature's earlier reverts, `interventions` the week's interventions on it.
- `arm` comes from the task's owner, the persona that took it: the foundry's Teams-path personas
  (`fable-opus`, `fable-sonnet`) are `teams`, the runner's (`builder`, `reviewer`) `autopilot`
  (agentvcs `docs/superpowers/notes/2026-11-05-foundry-runbook.md` section 6). The export carries
  no path, so any other owner is refused until `--arm OWNER=teams|autopilot` names it.
- Nothing that names a person or describes the work is copied: no title, target, actor, comment
  or task id. Slugs are published for every repository, private ones (agentvcs) included.

See docs/PREREG-ledger.md for what the ledger reports and what it does not claim.
"""

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import SCHEMA_VERSION, runfile
from .import_scholion import _provider

RUNNER = "scholion-cloud"
DATASET = "scholion-dev"
ARMS = ("autopilot", "teams")
DEFAULT_ARMS = {"fable-opus": "teams", "fable-sonnet": "teams", "builder": "autopilot", "reviewer": "autopilot"}
REPO_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
PREREG = "docs/PREREG-ledger.md"


class LedgerError(ValueError):
    """The export cannot become a ledger run as it is."""


def _instant(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def _z(d):
    return f"{d.isoformat()}T00:00:00Z"


def _week(rep, week):
    """The Monday the export covers, checked against `from`/`to` and `--week`."""
    if not rep.get("from") or not rep.get("to"):
        raise LedgerError("the export covers no week: export one, "
                          "GET /v1/ee/reports?repo=R&from=<Monday>&to=<Sunday>")
    start, end = _instant(rep["from"]), _instant(rep["to"])
    monday = start.date()
    if start != datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc) or monday.weekday() != 0:
        raise LedgerError(f"the export starts {rep['from']}, not a Monday at 00:00 UTC")
    if end - start != timedelta(days=7):
        raise LedgerError(f"the export covers {rep['from']} to {rep['to']}, not one week")
    if week is not None and date.fromisoformat(week) != monday:
        raise LedgerError(f"--week {week} is not the export's week ({monday})")
    return monday, start, end


def _repo(rep, repo):
    got = rep.get("repo")
    if not got:
        raise LedgerError("the export covers every repo: export one, GET /v1/ee/reports?repo=R")
    if repo is not None and repo != got:
        raise LedgerError(f"--repo {repo} is not the export's repo ({got})")
    if not REPO_RE.match(got):
        raise LedgerError(f"repo {got!r}: lowercase letters, digits and hyphens only")
    return got


def _get(d, *path):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _ledger(rep, repo, owners, models):
    s = rep.get("summary") or {}
    mem = s.get("memory_signal")
    return {
        "repo": repo,
        "from": _z(_instant(rep["from"]).date()),
        "to": _z(_instant(rep["to"]).date()),
        "features_merged": s.get("features_merged"),
        "feature_cost_usd": s.get("feature_cost_usd"),
        "cost_per_merged_feature_usd": s.get("cost_per_merged_feature_usd"),
        "spend_usd": s.get("spend_usd"),
        "spend_per_merged_feature_usd": s.get("spend_per_merged_feature_usd"),
        "unpriced_tokens": s.get("unpriced_tokens"),
        "reverts": s.get("reverts"),
        "escalations": s.get("escalations"),
        "gate_decisions": s.get("gate_decisions"),
        "human_interventions": s.get("human_interventions"),
        "backlog_to_merge_median_secs": _get(s, "backlog_to_merge", "median_secs"),
        "review_latency_median_secs": _get(s, "review_latency", "median_secs"),
        "gate_wait_median_secs": _get(s, "gate_wait", "median_secs"),
        "review_rounds_mean": _get(s, "review_rounds", "mean"),
        "runner_outcomes": [
            {k: r.get(k) for k in ("outcome", "sessions", "mean_wall_secs", "check_failed")}
            for r in rep.get("runner_outcomes") or [] if r.get("repo") in (repo, None)
        ],
        "memory_signal": None if not isinstance(mem, dict) else {
            k: mem.get(k) for k in ("records_written", "pack_tokens", "pack_items", "known_findings")
        },
        "owners": dict(sorted(owners.items())),
        "models": models,
    }


def convert(rep, repo=None, week=None, arms=None, revision=None, notes=None):
    """(run, sessions) for one export; raises LedgerError when it is not one repo and one week.

    `revision` (2, 3, ...) supersedes a published week: the id gets `.<revision>` and `notes` must
    say why; the site shows a week's highest revision."""
    repo = _repo(rep, repo)
    monday, start, end = _week(rep, week)
    table = {**DEFAULT_ARMS, **(arms or {})}
    bad = {a for a in table.values() if a not in ARMS}
    if bad:
        raise LedgerError(f"arm {sorted(bad)[0]!r}: an arm is teams or autopilot")
    run_id = f"{monday.isoformat()}-ledger-{repo}"
    if revision is not None:
        if revision < 2 or not (notes or "").strip():
            raise LedgerError("a revision is 2 or more and its --notes say why it supersedes the week")
        run_id += f".{revision}"

    per_task = {}
    for iv in rep.get("interventions") or []:
        if iv.get("task_id"):
            per_task[iv["task_id"]] = per_task.get(iv["task_id"], 0) + 1

    sessions, owners, models = [], {}, set()
    for f in rep.get("features") or []:
        if f.get("repo") != repo:
            raise LedgerError(f"feature {f.get('slug')!r} is in repo {f.get('repo')!r}, not {repo}")
        merged = _instant(f["merged_at"])
        if not start <= merged < end:
            raise LedgerError(f"feature {f['slug']!r} merged {f['merged_at']}, outside the week {monday}")
        owner = f.get("owner")
        if owner not in table:
            raise LedgerError(f"owner {owner!r} of {f['slug']!r} is on no path: "
                              f"pass --arm {owner}=teams or --arm {owner}=autopilot")
        owners[owner] = table[owner]
        models |= set((f.get("models") or "").split())
        wall, reason = f.get("backlog_to_merge_secs"), None
        if wall is None:
            wall = f.get("task_to_merge_secs") or 0.0
            reason = "not from the backlog: wall_secs is task to merge"
        sessions.append({
            "type": "session",
            "run_id": run_id,
            "task": f["slug"],
            "arm": table[owner],
            "attempt": 1 + int(f.get("reverts") or 0),
            "status": "ok",
            "reason": reason,
            "reward": 1.0,
            "accepted": True,
            "cost_usd": f.get("cost_usd"),
            "cost_source": "measured",
            "wall_secs": float(wall),
            "truncated": False,
            "interventions": per_task.get(f.get("task_id"), 0),
            "unpriced_tokens": f.get("unpriced_tokens"),
            "trajectory": {"kind": "none"},
        })

    arms_seen = sorted({s["arm"] for s in sessions})
    models = sorted(models)
    model = {"provider": _provider(models[0]), "name": models[0]} if len(models) == 1 else \
        {"provider": "multi", "name": "multi"}
    run = {
        "type": "run",
        "schema_version": SCHEMA_VERSION,
        "id": run_id,
        "date": _z(monday),
        "dataset": {"name": DATASET, "version": None, "rev": None, "visibility": "public"},
        "agent": {"name": RUNNER, "version": None},
        "model": model,
        "config": {"arm": arms_seen[0] if len(arms_seen) == 1 else "multi", "arms": arms_seen,
                   "attempts_per_task": None},
        "harness": {"runner": RUNNER},
        "machine": {"kind": "local", "os": None, "sandbox": None},
        "budget": None,
        "prereg": PREREG,
        "seed": None,
        "flags": [],
        "ledger": _ledger(rep, repo, owners, models),
        "source": None,
        "notes": notes,
    }
    return run, sessions


def import_file(path, out_dir, repo=None, week=None, arms=None, revision=None, notes=None):
    """Writes the ledger run for one export; never overwrites one (runs/ is append-only)."""
    rep = json.loads(Path(path).read_text(encoding="utf-8"))
    run, sessions = convert(rep, repo=repo, week=week, arms=arms, revision=revision, notes=notes)
    out = Path(out_dir) / f"{run['id']}.jsonl"
    if out.exists():
        raise LedgerError(f"{out.as_posix()} exists: runs are append-only; supersede it with "
                          "--revision N --notes WHY")
    return runfile.write(out, run, sessions)
