"""Runs the cross-vendor handoff benchmark (docs/PREREG-handoff-xvendor.md) on this host.

    uv run python -m oe.xvendor a     DIRECTION [--dry-run]      # predecessor A, one per task
    uv run python -m oe.xvendor freeze DIRECTION JOB...          # frozen A's (valid ones) into _shared
    uv run python -m oe.xvendor b     DIRECTION --arms repo-only,records [--rounds 5] [--dry-run]
    uv run python -m oe.xvendor spent                            # per vendor: priced spend, unfinished trials
    uv run python -m oe.xvendor report RUNFILE                   # the per-arm table of the results doc

Successor trials are launched one Harbor job per trial (one task directory, `-k 1`), in rounds:
round r runs every (task, arm) once before round r+1 starts, so a stop at the budget leaves the
cells balanced to within one round. Before each launch the vendor's spend so far (`oe budget`'s
pricing over its own jobs root), plus one per-trial ceiling for every trial in flight and every
job left without a result, plus one more ceiling, must stay within the vendor's cap. A trial whose
agent never started (a setup failure, such as Claude Code's installer failing its checksum) is
re-run once; nothing else is re-run. A finished trial is never launched again, so the command
resumes where it stopped.

Each vendor's legs get only their own endpoint and key: every ANTHROPIC_* variable and both keys
are removed from the environment Harbor gets, then the leg's own are set. Keys are read from the
environment by name and never printed.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

from . import REPO
from .budget import spent as priced_spend

CUT_TURNS = 4
WRAPUP_TURNS = 4
B_TURNS = 40
AV_RELEASE = "release/0.0.2"
TASKS = ("compound-discounts", "csv-escaping", "paginated-scan", "summarize-abbrev",
         "order-price-snapshot", "config-literal-values")
A_DATASETS = ("tallyho-cold", "tallyho-more")
ROOT = Path(os.environ.get("OE_XV_ROOT", "D:/oex"))  # short: the av arm's session paths pass 260 chars

VENDORS = {
    "claude": {"model": "anthropic/claude-sonnet-5-5", "cap": 20.00, "ceiling": 0.80,
               "ak": ["max_budget_usd=0.75"], "ae": []},
    "deepseek": {"model": "anthropic/deepseek-flash", "cap": 1.00, "ceiling": 0.05, "ak": [],
                 "ae": [f"{v}=deepseek-flash" for v in
                        ("ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_SMALL_FAST_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL")]},
}
DIRECTIONS = {  # named by A -> B; the family is named by A's model
    "sonnet-to-flash": {"family": "xv-sonnet", "a": "claude", "b": "deepseek"},
    "flash-to-sonnet": {"family": "xv-flash", "a": "deepseek", "b": "claude"},
}
AGENTS = {"repo-only": "claude-code", "notes": "claude-code", "records": "oe_agents.handoff_b:HandoffBAv"}
KEY_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_API_KEY", "DEEPSEEK_API_KEY")


def leg_env(vendor, base=None):
    """The environment for one vendor's Harbor run: only that vendor's endpoint and key."""
    src = dict(os.environ if base is None else base)
    env = {k: v for k, v in src.items() if k not in KEY_VARS}
    if vendor == "claude":
        env["ANTHROPIC_API_KEY"] = src["CLAUDE_API_KEY"]
    elif vendor == "deepseek":
        env["ANTHROPIC_BASE_URL"] = "https://api.deepseek.com/anthropic"
        env["ANTHROPIC_AUTH_TOKEN"] = src["DEEPSEEK_API_KEY"]
    else:
        raise ValueError(vendor)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(REPO / "agents")
    env["DOCKER_BUILDKIT"] = "0"  # BuildKit segfaults on RUN steps on this host
    env["COMPOSE_BAKE"] = "false"
    return env


def plan(arms, rounds, tasks=TASKS):
    """(round, task, arm) in launch order: every cell once per round."""
    return [(r, t, a) for r in range(1, rounds + 1) for t in tasks for a in arms]


def job_name(family, arm, task, rnd):
    return f"xv-b-{family}-{arm}-{task}-r{rnd}"


def trial_result(job_dir):
    """The trial result.json of a one-trial job, or None."""
    for p in sorted(Path(job_dir).glob("*/result.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if "trial_name" in r:
            return r
    return None


def setup_failure(r):
    """A trial that raised before its agent ran: re-run once (PREREG), never a result."""
    if not r or not r.get("exception_info"):
        return False
    return not (r.get("agent_execution") or {}).get("started_at")


def cell_state(root, family, arm, task, rnd):
    """("done", job) | ("retry", job) | ("todo", job) for one planned trial."""
    first = Path(root) / job_name(family, arm, task, rnd)
    second = first.with_name(first.name + "-retry")
    r1 = trial_result(first) if first.exists() else None
    if first.exists() and not setup_failure(r1) and r1 is not None:
        return "done", first
    if second.exists():
        return "done", second  # its result stands, whatever it is
    if first.exists() and r1 is None:
        return "done", first  # a killed trial: charged at the ceiling, not re-run
    if first.exists():
        return "retry", second
    return "todo", first


def unfinished(root):
    """Job dirs under root with no trial result (killed, or still running)."""
    root = Path(root)
    return [j for j in sorted(root.iterdir()) if j.is_dir() and trial_result(j) is None] if root.exists() else []


def vendor_spend(vendor, root=None):
    """(priced spend, unpriced trials, unfinished jobs) of one vendor's jobs root."""
    root = Path(root or ROOT / vendor)
    total, unpriced = priced_spend(root) if root.exists() else (0.0, 0)
    return total, unpriced, len(unfinished(root))


def may_launch(vendor, in_flight=0, root=None):
    """(ok, why): spend + ceilings for unfinished jobs, those in flight and one more must fit the cap."""
    v = VENDORS[vendor]
    total, unpriced, open_jobs = vendor_spend(vendor, root)
    if unpriced:
        return False, f"{unpriced} trial(s) without any price: stop and look"
    reserve = (max(open_jobs, in_flight) + 1) * v["ceiling"]
    if total + reserve > v["cap"]:
        return False, f"spent {total:.4f} + reserve {reserve:.2f} > cap {v['cap']:.2f}"
    return True, f"spent {total:.4f} + reserve {reserve:.2f} <= cap {v['cap']:.2f}"


def claude_version():
    out = subprocess.run("npm view @anthropic-ai/claude-code version", shell=True, capture_output=True, text=True)
    v = out.stdout.strip()
    if not v:
        raise SystemExit("npm view @anthropic-ai/claude-code version printed nothing")
    return v


def pinned_version():
    p = ROOT / "claude-code-version.txt"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(claude_version() + "\n", encoding="utf-8")
    return p.read_text(encoding="utf-8").strip()


def harbor_cmd(path, agent, model, job, root, ak=(), ae=(), include=None):
    cmd = ["uv", "run", "harbor", "run", "-p", str(path), "-a", agent, "-m", model, "-k", "1", "-n", "1",
           "-r", "0", "-o", str(root), "--job-name", job, "--agent-setup-timeout-multiplier", "2"]
    if include:
        cmd += ["-i", include]
    for x in ak:
        cmd += ["--ak", x]
    for x in ae:
        cmd += ["--ae", x]
    return cmd


def b_command(direction, arm, task, job):
    d = DIRECTIONS[direction]
    v = VENDORS[d["b"]]
    ak = [f"max_turns={B_TURNS}", f"version={pinned_version()}", *v["ak"]]
    if arm == "records":
        ak.append(f"av_version={AV_RELEASE}")
    path = REPO / "datasets" / f"handoff-{d['family']}" / f"{task}--{arm}"
    return harbor_cmd(path, AGENTS[arm], v["model"], job, ROOT / d["b"], ak, v["ae"])


def write_env(job_dir, direction, arm):
    d = DIRECTIONS[direction]
    job_dir.mkdir(parents=True, exist_ok=True)
    rev = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    (job_dir / "oe-env.json").write_text(json.dumps({
        "dataset": f"handoff-{d['family']}", "attempts": None, "sandbox": "docker", "os": "windows",
        "openevaluations_rev": rev.stdout.strip() or None, "prereg": "docs/PREREG-handoff-xvendor.md",
        "scholion_rev": AV_RELEASE if arm == "records" else None,
        "budget": {"cap_usd": VENDORS[d["b"]]["cap"], "spent_usd": None}}), encoding="utf-8")


def _log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def run_b(direction, arms, rounds, parallel=1, dry_run=False, tasks=TASKS):
    d = DIRECTIONS[direction]
    vendor, root = d["b"], ROOT / d["b"]
    root.mkdir(parents=True, exist_ok=True)
    present = [t for t in tasks if (REPO / "datasets" / f"handoff-{d['family']}" / f"{t}--{arms[0]}").exists()]
    queue = []
    for rnd, task, arm in plan(arms, rounds, present):
        state, job = cell_state(root, d["family"], arm, task, rnd)
        if state != "done":
            queue.append((rnd, task, arm, job))
    _log(f"{direction}: {len(queue)} trial(s) to run ({len(present)} tasks x {arms} x {rounds} rounds)")
    running = []
    while queue or running:
        running = [(p, j) for p, j in running if p.poll() is None]
        if queue and len(running) < parallel:
            ok, why = may_launch(vendor, in_flight=len(running), root=root)
            if not ok:
                _log(f"stop launching ({vendor}): {why}")
                queue = []
                continue
            rnd, task, arm, job = queue.pop(0)
            cmd = b_command(direction, arm, task, job.name)
            _log(f"launch r{rnd} {task}--{arm} -> {job.name} ({why})")
            if dry_run:
                print("  " + " ".join(cmd))
                continue
            write_env(job, direction, arm)
            log = open(root / f"{job.name}.log", "w", encoding="utf-8")
            running.append((subprocess.Popen(cmd, cwd=REPO, env=leg_env(vendor), stdout=log,
                                             stderr=subprocess.STDOUT), job))
            continue
        time.sleep(5)
    total, unpriced, open_jobs = vendor_spend(vendor, root)
    _log(f"{direction} done: {vendor} spent {total:.4f} (unpriced {unpriced}, unfinished {open_jobs})")


def run_a(direction, dry_run=False, suffix=""):
    d = DIRECTIONS[direction]
    vendor, root = d["a"], ROOT / d["a"]
    v = VENDORS[vendor]
    root.mkdir(parents=True, exist_ok=True)
    frozen = REPO / "datasets" / "_shared" / "handoff" / d["family"]
    done = {p.name for p in frozen.iterdir() if p.is_dir()} if frozen.exists() else set()
    for ds in A_DATASETS:
        todo = [t for t in TASKS if (REPO / "datasets" / ds / t).exists() and t not in done]
        if not todo:
            continue
        total, unpriced, open_jobs = vendor_spend(vendor, root)
        reserve = (open_jobs + 2 * len(todo)) * v["ceiling"]  # an A is two Claude Code runs (cut, wrap-up)
        if unpriced or total + reserve > v["cap"]:
            raise SystemExit(f"A {direction} {ds}: spent {total:.4f} + reserve {reserve:.2f} > cap {v['cap']} "
                             f"(or {unpriced} unpriced)")
        job = f"xv-a-{d['family']}-{ds}{suffix}"
        ak = [f"max_turns={CUT_TURNS}", f"wrapup_turns={WRAPUP_TURNS}", f"version={pinned_version()}",
              f"av_version={AV_RELEASE}", *v["ak"]]
        cmd = harbor_cmd(REPO / "datasets" / ds, "oe_agents.handoff_a:HandoffA", v["model"], job, root, ak, v["ae"])
        for t in TASKS:
            if (REPO / "datasets" / ds / t).exists() and t not in todo:
                cmd += ["-x", f"*{t}"]
        _log(f"A {direction} {ds}: {todo} -> {job}")
        if dry_run:
            print("  " + " ".join(cmd))
            continue
        with open(root / f"{job}.log", "w", encoding="utf-8") as log:
            subprocess.run(cmd, cwd=REPO, env=leg_env(vendor), stdout=log, stderr=subprocess.STDOUT)


def freeze(direction, jobs):
    """oe freeze each A job into a scratch dir, then copy only the valid A's into _shared (never replacing one)."""
    from . import handoff

    d = DIRECTIONS[direction]
    dest = REPO / "datasets" / "_shared" / "handoff" / d["family"]
    dest.mkdir(parents=True, exist_ok=True)
    scratch = ROOT / "frozen" / d["family"]
    for job in jobs:
        for res in sorted(Path(job).glob("*/result.json")):
            r = json.loads(res.read_text(encoding="utf-8"))
            if "trial_name" not in r:
                continue
            a = handoff.freeze(res.parent, scratch / r["trial_name"], cut_turns=CUT_TURNS)
            src = scratch / r["trial_name"] / a["task"]
            print(json.dumps({k: a.get(k) for k in ("task", "valid", "problems", "a_turns", "a_stop", "wrapup_turns",
                                                    "wrapup_changed_files", "files_changed", "records", "a_reward")}))
            if a["valid"] and not (dest / a["task"]).exists():
                import shutil

                shutil.copytree(src, dest / a["task"])


def _agent_ran(s):
    return s["status"] == "ok" or (s["status"] == "error" and s.get("error_class") in (
        "NonZeroAgentExitCodeError", "AgentTimeoutError"))


def report(runfile_path):
    """Per arm: n (sessions whose agent ran and that are valid), solved, rate, cost per solved, median turns."""
    from . import runfile

    run, sessions = runfile.read(runfile_path)
    rows = []
    for arm in run["config"]["arms"]:
        ss = [s for s in sessions if s["arm"] == arm]
        valid = [s for s in ss if _agent_ran(s)]
        solved = [s for s in valid if (s.get("reward") or 0) >= 1.0]
        costs = [s["cost_usd"] for s in valid if s.get("cost_usd") is not None]
        turns = [s["turns"] for s in valid if s.get("turns") is not None]
        rows.append({
            "arm": arm, "n": len(valid), "invalid": sum(s["status"] == "invalid" for s in ss),
            "other_errors": sum(s["status"] == "error" and not _agent_ran(s) for s in ss),
            "solved": len(solved), "rate": len(solved) / len(valid) if valid else None,
            "cost_total": sum(costs), "cost_per_solved": sum(costs) / len(solved) if solved else None,
            "median_turns": statistics.median(turns) if turns else None,
            "cost_sources": sorted({s["cost_source"] for s in valid}),
        })
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(prog="oe.xvendor")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("a")
    a.add_argument("direction", choices=DIRECTIONS)
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--suffix", default="", help="job name suffix (the one re-run of invalid A's)")
    f = sub.add_parser("freeze")
    f.add_argument("direction", choices=DIRECTIONS)
    f.add_argument("jobs", nargs="+")
    b = sub.add_parser("b")
    b.add_argument("direction", choices=DIRECTIONS)
    b.add_argument("--arms", default="repo-only,records")
    b.add_argument("--rounds", type=int, default=5)
    b.add_argument("--parallel", type=int, default=1)
    b.add_argument("--dry-run", action="store_true")
    sub.add_parser("spent")
    r = sub.add_parser("report")
    r.add_argument("runfile")
    args = p.parse_args(argv)
    if args.cmd == "a":
        run_a(args.direction, args.dry_run, args.suffix)
    elif args.cmd == "freeze":
        freeze(args.direction, args.jobs)
    elif args.cmd == "b":
        run_b(args.direction, args.arms.split(","), args.rounds, args.parallel, args.dry_run)
    elif args.cmd == "spent":
        for vendor in VENDORS:
            total, unpriced, open_jobs = vendor_spend(vendor)
            print(f"{vendor}: spent {total:.4f} of {VENDORS[vendor]['cap']:.2f}; unpriced {unpriced}; "
                  f"unfinished jobs {open_jobs}")
    elif args.cmd == "report":
        print(json.dumps(report(args.runfile), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
