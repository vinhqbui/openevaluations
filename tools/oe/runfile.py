"""Reading and writing runs/<id>.jsonl: line 1 is the run, every other line a session."""

import json
from pathlib import Path


def read(path):
    lines = [l for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        raise ValueError(f"{path}: empty")
    recs = [json.loads(l) for l in lines]
    return recs[0], recs[1:]


def dumps(rec):
    return json.dumps(rec, ensure_ascii=False, separators=(",", ":"))


def write(path, run, sessions):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(dumps(r) for r in [run, *sessions]) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def load_all(runs_dir):
    """Every run file under runs_dir, sorted by (date, id): [{run, sessions, path}]."""
    out = []
    for p in sorted(Path(runs_dir).glob("*.jsonl")):
        run, ss = read(p)
        out.append({"run": run, "sessions": ss, "path": p})
    out.sort(key=lambda r: (r["run"]["date"], r["run"]["id"]))
    return out
