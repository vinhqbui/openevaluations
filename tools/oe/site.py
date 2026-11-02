"""Builds site/data/*.json (and copies raw run files) from runs/*.jsonl.

Output is deterministic (sorted keys, rounded floats), so `oe site --check` can fail CI when the
committed data is stale.
"""

import json
import shutil
import tempfile
from pathlib import Path

from . import REPO, runfile, stats

# How scholion's relay arms map onto the handoff benchmark's channels.
RELAY_CHANNELS = {
    "cold": "repo-only",
    "baseline": "git-log",
    "notes": "notes",
    "av": "records (Scholion)",
}


def _round(x):
    if isinstance(x, float):
        return round(x, 6)
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_round(v) for v in x]
    return x


def _dump(obj, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_round(obj), sort_keys=True, indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")


def _arms(sessions):
    by = {}
    for s in sessions:
        by.setdefault(s["arm"], []).append(s)
    return by


def _series_key(run):
    return f"{run['dataset']['name']}|{run['agent']['name']}|{run['model']['name']}"


def _cold_for(run, points, day):
    """The cold arm an arm of `run` is paired with: the run's own, else the one cold-only run of
    the same series that day (preferring the same source). None when there is none or it is
    ambiguous, so an arm is never paired with a cold arm from an unrelated run."""
    if "cold" in points:
        return points["cold"]
    others = [(r, p) for r, p in day if r is not run and set(p) == {"cold"}]
    if run.get("source"):
        same = [x for x in others if x[0].get("source") == run["source"]]
        others = same or others
    return others[0][1]["cold"] if len(others) == 1 else None


def build(runs_dir, out_dir):
    runs = runfile.load_all(runs_dir)
    out_dir = Path(out_dir)
    index, series, handoff = [], {}, []
    by_day = {}  # (series key, day) -> [(run, {arm: (point, sessions)})], to pair arms with a cold arm
    datasets = {}
    for r in runs:
        run, ss = r["run"], r["sessions"]
        private = run["dataset"]["visibility"] == "private"
        per_arm = {arm: stats.summary(v) for arm, v in sorted(_arms(ss).items())}
        if private:
            per_arm = {run["config"]["arm"]: dict(run["aggregate"], rate=None)}
        index.append({
            "id": run["id"], "date": run["date"], "dataset": run["dataset"]["name"],
            "visibility": run["dataset"]["visibility"], "agent": run["agent"], "model": run["model"],
            "runner": run["harness"]["runner"], "flags": run["flags"], "source": run.get("source"),
            "prereg": run.get("prereg"), "arms": per_arm,
            "raw": None if private else f"/data/runs/{run['id']}.jsonl",
        })
        ds = datasets.setdefault(run["dataset"]["name"], {"runs": 0, "sessions": 0, "tasks": set(), "agents": set()})
        ds["runs"] += 1
        ds["sessions"] += len(ss)
        ds["tasks"] |= {s["task"] for s in ss}
        ds["agents"].add(run["agent"]["name"])

        key = _series_key(run)
        sr = series.setdefault(key, {"key": key, "dataset": run["dataset"]["name"], "agent": run["agent"]["name"],
                                     "model": run["model"]["name"], "arms": {}})
        arms_ss, points = _arms(ss), {}
        for arm, summ in per_arm.items():
            point = {"run_id": run["id"], "date": run["date"], "agent_version": run["agent"]["version"],
                     "flags": run["flags"], **summ}
            sr["arms"].setdefault(arm, []).append(point)
            points[arm] = (point, arms_ss.get(arm, []))
        if not private:
            by_day.setdefault((key, run["date"][:10]), []).append((run, points))

        if run["dataset"]["name"] in ("scholion-relay", "handoff") and not private:
            arms = _arms(ss)
            base = arms.get("cold") or arms.get("repo-only")
            cells = []
            for arm, v in sorted(arms.items()):
                cell = {"arm": arm, "channel": RELAY_CHANNELS.get(arm, arm), **stats.summary(v)}
                if base is not None and v is not base:
                    p = stats.paired_report(base, v)
                    cell["vs_repo_only"] = {"cost": p["cost"], "tokens": p["tokens"], "turns": p["turns"]}
                cells.append(cell)
            handoff.append({"run_id": run["id"], "date": run["date"], "family": "relay" if run["dataset"]["name"] == "scholion-relay" else "interrupt",
                            "successor": run["agent"], "model": run["model"], "runner": run["harness"]["runner"],
                            "prereg": run.get("prereg"), "source": run.get("source"), "cells": cells})

    for day in by_day.values():
        for run, points in day:
            base = _cold_for(run, points, day)
            if base is None:
                continue
            for arm, (point, arm_ss) in points.items():
                if arm != "cold" and arm_ss:
                    p = stats.paired_report(base[1], arm_ss)
                    point["vs_cold"] = {"cost": p["cost"], "tokens": p["tokens"], "turns": p["turns"],
                                        "cold_run_id": base[0]["run_id"]}

    _dump({"runs": index[::-1]}, out_dir / "runs.json")
    _dump({"series": [series[k] for k in sorted(series)]}, out_dir / "tracker.json")
    _dump({"runs": handoff[::-1]}, out_dir / "handoff.json")
    _dump({"datasets": {k: {"runs": v["runs"], "sessions": v["sessions"], "tasks": sorted(v["tasks"]),
                            "agents": sorted(v["agents"])} for k, v in sorted(datasets.items())}},
          out_dir / "datasets.json")
    raw = out_dir / "runs"
    if raw.exists():
        shutil.rmtree(raw)
    raw.mkdir(parents=True)
    for r in runs:
        if r["run"]["dataset"]["visibility"] == "public":
            shutil.copyfile(r["path"], raw / r["path"].name)
    sch = out_dir / "schema"
    sch.mkdir(exist_ok=True)
    for f in sorted((REPO / "schema").glob("*.schema.json")):
        shutil.copyfile(f, sch / f.name)
    return out_dir


def check(runs_dir, out_dir):
    """Problems if out_dir is not what build() would write now."""
    with tempfile.TemporaryDirectory() as tmp:
        fresh = build(runs_dir, Path(tmp) / "data")
        problems = []
        for p in fresh.rglob("*"):
            if p.is_file():
                q = Path(out_dir) / p.relative_to(fresh)
                if not q.exists():
                    problems.append(f"missing: {p.relative_to(fresh).as_posix()}")
                elif q.read_bytes() != p.read_bytes():
                    problems.append(f"stale: {p.relative_to(fresh).as_posix()}")
        for q in Path(out_dir).rglob("*"):
            if q.is_file() and not (fresh / q.relative_to(out_dir)).exists():
                problems.append(f"extra: {q.relative_to(out_dir).as_posix()}")
        return sorted(set(problems))
