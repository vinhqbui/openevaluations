"""Validates run files against schema/*.schema.json plus the rules JSON Schema cannot say."""

import json
import re
from datetime import date
from functools import cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from . import REPO


@cache
def _validator(name):
    schema = json.loads((REPO / "schema" / f"{name}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _errs(name, rec, where):
    return [
        f"{where}: {'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
        for e in sorted(_validator(name).iter_errors(rec), key=lambda e: list(map(str, e.path)))
    ]


LEDGER_ID = re.compile(r"^(\d{4}-\d{2}-\d{2})-ledger-([a-z0-9][a-z0-9-]*?)(?:\.(\d+))?$")
LEDGER_ARMS = ("autopilot", "teams")
# A Scholion task slug: lowercase letters and digits in hyphen-separated words (scholion's
# `slugify`, plus its `-2` suffix). A title, with its spaces and capitals, never matches.
SLUG = re.compile(r"^[^\W_]+(?:-[^\W_]+)*$")


def _ledger_errs(name, run, sessions):
    """The ledger's rule (harness.runner scholion-cloud): see schema/README.md."""
    errs = []
    if run.get("harness", {}).get("runner") != "scholion-cloud":
        if "ledger" in run:
            errs.append(f"{name}: only a scholion-cloud (ledger) run carries a ledger")
        return errs
    lg = run.get("ledger")
    if not isinstance(lg, dict):
        return [f"{name}: a scholion-cloud run needs its ledger object"]
    if run.get("dataset", {}).get("name") != "scholion-dev":
        errs.append(f"{name}: a ledger run's dataset is scholion-dev")
    if run.get("dataset", {}).get("visibility") != "public":
        errs.append(f"{name}: a ledger run is public: its sessions carry slugs, never titles")
    m = LEDGER_ID.match(run.get("id") or "")
    if not m:
        errs.append(f"{name}: a ledger run's id is <week>-ledger-<repo>[.<revision>]")
    else:
        week = date.fromisoformat(m.group(1))
        if week.weekday() != 0:
            errs.append(f"{name}: a ledger week starts on a Monday, not {week}")
        if m.group(2) != lg.get("repo"):
            errs.append(f"{name}: the id names repo {m.group(2)!r}, the ledger {lg.get('repo')!r}")
        if not str(run.get("date", "")).startswith(m.group(1)) or not str(lg.get("from", "")).startswith(m.group(1)):
            errs.append(f"{name}: the run's date and ledger.from are the week's Monday, {m.group(1)}")
    if lg.get("features_merged") != len(sessions):
        errs.append(f"{name}: ledger.features_merged is {lg.get('features_merged')}, "
                    f"but there are {len(sessions)} sessions (one per merged feature)")
    for i, s in enumerate(sessions, start=2):
        where = f"{name}:{i}"
        if s.get("arm") not in LEDGER_ARMS:
            errs.append(f"{where}: a ledger arm is teams or autopilot, not {s.get('arm')!r}")
        if not (s.get("status") == "ok" and s.get("accepted") is True):
            errs.append(f"{where}: a ledger session is a merged feature: status ok, accepted")
        if s.get("cost_source") != "measured" or not isinstance(s.get("cost_usd"), (int, float)):
            errs.append(f"{where}: a ledger cost is measured (priced_usage): cost_source measured and a cost_usd")
        task = s.get("task") or ""
        if not SLUG.match(task) or task != task.lower():
            errs.append(f"{where}: task {task!r} is not a slug; a ledger publishes slugs, never titles")
        if not isinstance(s.get("interventions"), int):
            errs.append(f"{where}: a ledger session counts its interventions")
    return errs


def validate_file(path):
    """A list of problems; empty means the file is valid."""
    path = Path(path)
    try:
        lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        recs = [json.loads(l) for l in lines]
    except (OSError, ValueError) as e:
        return [f"{path.name}: {e}"]
    if not recs or recs[0].get("type") != "run":
        return [f"{path.name}: line 1 must be the run record"]
    run, sessions = recs[0], recs[1:]
    errs = _errs("run", run, f"{path.name}:1")
    if path.stem != run.get("id"):
        errs.append(f"{path.name}: file name must be <run id>.jsonl (id is {run.get('id')!r})")
    private = run.get("dataset", {}).get("visibility") == "private"
    if private:
        if sessions:
            errs.append(f"{path.name}: a private dataset publishes the run line and its aggregate only, no sessions")
        if "aggregate" not in run:
            errs.append(f"{path.name}: a private dataset run needs an aggregate")
    errs += _ledger_errs(path.name, run, sessions)
    seen = set()
    for i, s in enumerate(sessions, start=2):
        errs += _errs("session", s, f"{path.name}:{i}")
        if s.get("run_id") != run.get("id"):
            errs.append(f"{path.name}:{i}: run_id {s.get('run_id')!r} is not this run's id")
        key = (s.get("task"), s.get("arm"), s.get("attempt"))
        if key in seen:
            errs.append(f"{path.name}:{i}: duplicate (task, arm, attempt) {key}")
        seen.add(key)
        if s.get("accepted") and s.get("status") != "ok":
            errs.append(f"{path.name}:{i}: only an ok session can be accepted")
    return errs


def validate_dir(runs_dir):
    errs = []
    for p in sorted(Path(runs_dir).glob("*.jsonl")):
        errs += validate_file(p)
    return errs
