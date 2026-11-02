"""Validates run files against schema/*.schema.json plus the rules JSON Schema cannot say."""

import json
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
