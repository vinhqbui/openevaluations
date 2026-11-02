"""Imports one Harbor job directory (<jobs>/<job>/) as one oe/1 run file.

Trial layout (Harbor TrialPaths): <trial>/{config.json, result.json, agent/trajectory.json,
agent/claude-code.txt|codex.txt, verifier/reward.txt}. TrialResult fields used: task_name,
trial_name, agent_info{name, version, model_info{name, provider}}, agent_result{n_input_tokens,
n_cache_tokens, n_output_tokens, cost_usd, metadata}, verifier_result{rewards},
exception_info{exception_type}, started_at, agent_execution{started_at, finished_at}.
"""

import hashlib
import json
import platform
import tomllib
from datetime import datetime
from pathlib import Path

from . import SCHEMA_VERSION, atif, runfile
from .budget import trial_cost
from .import_scholion import _provider


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _reward(vr):
    rw = (vr or {}).get("rewards")
    if not rw:
        return 0.0
    if "reward" in rw:
        return float(rw["reward"])
    return float(next(iter(rw.values())))


def _truncated(agent_dir):
    for name in ("claude-code.txt", "codex.txt"):
        p = agent_dir / name
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
            return '"type":"result"' not in text.replace(" ", "") and '"turn.completed"' not in text
    return False


def _cli_turns(agent_dir):
    """num_turns from Claude Code's last stream-json result line; Harbor does not keep it."""
    p = agent_dir / "claude-code.txt"
    if not p.exists():
        return None
    turns = None
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if '"result"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("type") == "result" and isinstance(d.get("num_turns"), int):
            turns = d["num_turns"]
    return turns


def _dead_ends(task_dir):
    if not task_dir:
        return []
    p = Path(task_dir) / "task.toml"
    if not p.exists():
        return []
    meta = tomllib.loads(p.read_text(encoding="utf-8")).get("metadata", {})
    return meta.get("dead_ends", [])


def _task_dir(trial_cfg):
    t = (trial_cfg or {}).get("task") or {}
    path = t.get("path") if isinstance(t, dict) else None
    return path if path and Path(path).exists() else None


def _model_provider(mi):
    """The model's real provider: Harbor says "anthropic" for any model behind ANTHROPIC_BASE_URL."""
    name, prov = mi.get("name") or "", mi.get("provider") or "unknown"
    guessed = _provider(name)
    return guessed if guessed != "anthropic" or name.startswith("claude") else prov


def trials(job_dir):
    for res in sorted(Path(job_dir).glob("*/result.json")):
        r = json.loads(res.read_text(encoding="utf-8"))
        if "trial_name" in r:
            yield res.parent, r


def import_job(job_dir, out_dir, machine="local", dataset=None, arm=None, task_root=None):
    job_dir = Path(job_dir)
    rows = list(trials(job_dir))
    if not rows:
        raise SystemExit(f"{job_dir}: no trial result.json found")
    env = {}
    if (job_dir / "oe-env.json").exists():
        env = json.loads((job_dir / "oe-env.json").read_text(encoding="utf-8"))
    # Run-level agent and model from a trial that got past setup (a failed install says "unknown").
    infos = [r.get("agent_info") or {} for _, r in rows]
    info = next((i for i in infos if i.get("version") not in (None, "unknown")), infos[0])
    mi = info.get("model_info") or {}
    dataset = dataset or env.get("dataset") or job_dir.name
    arm = arm or env.get("arm") or info.get("name", "agent")
    starts = [_ts(r.get("started_at")) for _, r in rows if r.get("started_at")]
    date = min(starts) if starts else datetime.now()
    digest = hashlib.sha1("".join(sorted(r["trial_name"] for _, r in rows)).encode()).hexdigest()[:6]
    agent_name = info.get("name", "agent")
    rid = "-".join([_iso(date)[:10], dataset, agent_name] + ([arm] if arm != agent_name else []) + [digest])
    run = {
        "type": "run", "schema_version": SCHEMA_VERSION, "id": rid, "date": _iso(date),
        "dataset": {"name": dataset, "version": env.get("dataset_version"), "rev": env.get("dataset_rev"),
                    "visibility": env.get("visibility", "public")},
        "agent": {"name": info.get("name", "unknown"), "version": info.get("version")},
        "model": {"provider": _model_provider(mi), "name": mi.get("name") or "unknown"},
        "config": {"arm": arm, "arms": [arm], "agent_kwargs": env.get("agent_kwargs", {}),
                   "attempts_per_task": env.get("attempts")},
        "harness": {"runner": "harbor", "harbor_version": env.get("harbor_version"),
                    "openevaluations_rev": env.get("openevaluations_rev"), "agent_impl_rev": env.get("agent_impl_rev"),
                    "scholion_rev": env.get("scholion_rev")},
        "machine": {"kind": machine, "os": env.get("os") or platform.system().lower(), "sandbox": env.get("sandbox", "docker")},
        "budget": env.get("budget"), "prereg": env.get("prereg"), "seed": None, "flags": [],
        "source": env.get("source"),
    }
    by_task = {}
    for d, r in rows:
        by_task.setdefault(r["task_name"].split("/")[-1], []).append((d, r))
    sessions = []
    for task, items in sorted(by_task.items()):
        items.sort(key=lambda x: x[1].get("started_at") or "")
        for attempt, (d, r) in enumerate(items, start=1):
            ar = r.get("agent_result") or {}
            meta = ar.get("metadata") or {}
            exc = r.get("exception_info")
            status = "error" if exc else ("invalid" if meta.get("oe_invalid") else "ok")
            reward = _reward(r.get("verifier_result"))
            n_in, n_cache, n_out = ar.get("n_input_tokens"), ar.get("n_cache_tokens"), ar.get("n_output_tokens")
            inp = None if n_in is None else n_in - (n_cache or 0)
            cost, cs = trial_cost(r)
            traj_path = d / "agent" / "trajectory.json"
            traj = atif.load(traj_path)
            ae = r.get("agent_execution") or {}
            t0, t1 = _ts(ae.get("started_at")), _ts(ae.get("finished_at"))
            task_dir = Path(task_root) / task if task_root else _task_dir(json.loads((d / "config.json").read_text(encoding="utf-8")) if (d / "config.json").exists() else None)
            dead = _dead_ends(task_dir)
            sessions.append({
                "type": "session", "run_id": rid, "task": task, "arm": arm, "attempt": attempt,
                "status": status, "reason": meta.get("oe_invalid") or (exc or {}).get("exception_message"),
                "reward": reward, "accepted": status == "ok" and reward >= 1.0,
                "cost_usd": cost, "cost_source": cs,
                "tokens": {"input": inp, "output": n_out, "cache_read": n_cache, "cache_write": None},
                "tokens_billed": None if inp is None or n_out is None else inp + n_out,
                "llm_calls": atif.llm_calls(traj) if traj else None,
                "turns": meta.get("num_turns") or _cli_turns(d / "agent"),
                "tool_calls": atif.tool_calls(traj) if traj else None,
                "repeated_dead_ends": atif.repeated_dead_ends(traj, dead) if traj and dead else None,
                "wall_secs": (t1 - t0).total_seconds() if t0 and t1 else 0.0,
                "truncated": _truncated(d / "agent"),
                "error_class": (exc or {}).get("exception_type"),
                "trajectory": {"kind": "atif" if traj else "none",
                               "path": f"{job_dir.name}/{d.name}/agent/trajectory.json" if traj else None},
                "trial_name": r["trial_name"],
            })
    return runfile.write(Path(out_dir) / f"{rid}.jsonl", run, sessions)
