"""`oe`: validate, import, analyse and publish openevaluations runs."""

import argparse
import json
import sys
from pathlib import Path

from . import REPO, runfile, schema, site, stats


def _validate(a):
    errs = []
    for p in a.paths:
        p = Path(p)
        errs += schema.validate_dir(p) if p.is_dir() else schema.validate_file(p)
    for e in errs:
        print(e, file=sys.stderr)
    n = sum(len(list(Path(p).glob("*.jsonl"))) if Path(p).is_dir() else 1 for p in a.paths)
    print(f"{n} run file(s), {len(errs)} problem(s)")
    return 1 if errs else 0


def _import_scholion(a):
    from .import_scholion import import_tree

    written = import_tree(a.results, a.out, source_url=a.source_url)
    for p in written:
        print(p.as_posix())
    print(f"{len(written)} run file(s) written")
    return 0


def _import_harbor(a):
    from .import_harbor import import_job

    for job in ([a.jobs] if a.merge else a.jobs):
        p = import_job(job, a.out, machine=a.machine, dataset=a.dataset, arm=a.arm, channels=a.channels)
        print(p.as_posix())
    return 0


def _import_reports(a):
    from .import_reports import LedgerError, import_file

    arms = {}
    for spec in a.arm or []:
        owner, sep, arm = spec.partition("=")
        if not sep or not owner:
            print(f"--arm {spec}: OWNER=teams or OWNER=autopilot", file=sys.stderr)
            return 2
        arms[owner] = arm
    try:
        p = import_file(a.reports, a.out, repo=a.repo, week=a.week, arms=arms,
                        revision=a.revision, notes=a.notes)
    except LedgerError as e:
        print(f"{a.reports}: {e}", file=sys.stderr)
        return 1
    print(p.as_posix())
    return 0


def _freeze(a):
    from .handoff import freeze
    from .import_harbor import trials

    seen, bad = set(), 0
    for d, r in trials(a.job):
        task = r["task_name"].split("/")[-1]
        if task in seen:
            raise SystemExit(f"{a.job}: more than one A trial for {task}; A runs once per task (-k 1)")
        seen.add(task)
        fa = freeze(d, a.out, cut_turns=a.cut_turns)
        bad += not fa["valid"]
        state = "valid" if fa["valid"] else "INVALID: " + "; ".join(fa["problems"])
        print(f"{task}: {state}; changed {fa['files_changed']}, {fa['records']} record(s), "
              f"stopped at turn {fa['a_turns']} ({fa['a_stop']})")
    print(f"{len(seen)} A(s) frozen into {Path(a.out).as_posix()}, {bad} invalid")
    return 1 if bad else 0


def _rewards(a):
    from .import_harbor import _reward, trials

    rows = list(trials(a.job))
    bad = [(r["task_name"], _reward(r.get("verifier_result")), (r.get("exception_info") or {}).get("exception_type"))
           for _, r in rows]
    bad = [b for b in bad if b[2] or b[1] != a.expect]
    for task, reward, exc in bad:
        print(f"{task}: reward {reward}" + (f", {exc}" if exc else ""))
    print(f"{len(rows) - len(bad)}/{len(rows)} trial(s) scored {a.expect:g}")
    return 1 if bad or not rows else 0


def _fmt(x, pct=False):
    if x is None:
        return "-"
    return f"{x:+.1%}" if pct else (f"{x:.4g}" if isinstance(x, float) else str(x))


def _stats(a):
    if a.paired:
        _, base = runfile.read(a.paired[0])
        for spec in a.paired[1:]:
            path, _, arm = spec.partition(":")
            _, ss = runfile.read(path)
            if arm:
                ss = [s for s in ss if s["arm"] == arm]
            print(f"{spec} vs {a.paired[0]}")
            for m, (p, lo, hi) in stats.paired_report(base, ss).items():
                print(f"   {m:15} {_fmt(p, True):>7}  95% CI [{_fmt(lo, True)}, {_fmt(hi, True)}]")
        return 0
    for path in a.files:
        run, ss = runfile.read(path)
        by = {}
        for s in ss:
            by.setdefault(s["arm"], []).append(s)
        print(f"{run['id']}  {run['agent']['name']} {run['agent']['version']}  {run['model']['name']}")
        for arm, v in sorted(by.items()):
            s = stats.summary(v)
            note = "" if s["n"] >= stats.NO_CLAIM_BELOW else "  (n < 30: no significance claimed)"
            print(f"   {arm:12} accepted {s['accepted']}/{s['n']}  Wilson [{s['wilson'][0]:.2f}, {s['wilson'][1]:.2f}]"
                  f"  cost/accepted {_fmt(s['cost_per_accepted'])}  median turns {_fmt(s['median_turns'])}{note}")
    return 0


def _detect(a):
    runs = runfile.load_all(a.runs)
    hist = {}
    changed = 0
    for r in runs:
        run = r["run"]
        if run["dataset"]["visibility"] == "private" or run["harness"]["runner"] == "scholion-cloud":
            continue  # private runs publish no sessions; ledger runs are no tracker series
        key = (run["dataset"]["name"], run["agent"]["name"], run["model"]["name"], run["config"]["arm"])
        prev = hist.setdefault(key, [])
        flags = sorted(set(stats.detect_change(r, prev)) | (set(run["flags"]) & {"budget_stopped"}))
        if flags != run["flags"]:
            run["flags"] = flags
            runfile.write(r["path"], run, r["sessions"])
            changed += 1
            print(f"{run['id']}: {flags}")
        prev.append(r)
    print(f"{changed} run(s) re-flagged")
    return 0


def _site(a):
    out = Path(a.out)
    if a.check:
        problems = site.check(a.runs, out)
        for p in problems:
            print(p, file=sys.stderr)
        print("site data up to date" if not problems else f"{len(problems)} stale file(s); run `oe site`")
        return 1 if problems else 0
    site.build(a.runs, out)
    print(f"wrote {out.as_posix()}")
    return 0


def _budget(a):
    from .budget import spent

    total, unpriced = spent(a.jobs)
    print(json.dumps({"spent_usd": round(total, 4), "unpriced_trials": unpriced, "cap_usd": a.cap}))
    return 1 if a.cap is not None and total + a.reserve > a.cap else 0


def _tiers(a):
    from .tiers import load_tiers, markdown, tier_tables

    picked = [r for r in runfile.load_all(a.runs) if a.prereg and r["run"].get("prereg") == a.prereg]
    paths = {r["path"].resolve() for r in picked}
    picked += [{"path": Path(p), **dict(zip(("run", "sessions"), runfile.read(p))) } for p in a.also or []
               if Path(p).resolve() not in paths]
    print(markdown(tier_tables([(r["run"], r["sessions"]) for r in picked], load_tiers())), end="")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="oe", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="check run files against schema/ (oe/1)")
    p.add_argument("paths", nargs="*", default=[str(REPO / "runs")])
    p.set_defaults(fn=_validate)

    p = sub.add_parser("import-scholion", help="convert scholion bench/results into run files")
    p.add_argument("results", help="scholion's bench/results directory")
    p.add_argument("--out", default=str(REPO / "runs"))
    p.add_argument("--source-url", default="https://github.com/vinhqbui/scholion/tree/main/bench/results")
    p.set_defaults(fn=_import_scholion)

    p = sub.add_parser("import-harbor", help="convert Harbor job directories into run files")
    p.add_argument("jobs", nargs="+")
    p.add_argument("--out", default=str(REPO / "runs"))
    p.add_argument("--machine", default="local", choices=["local", "github-actions"])
    p.add_argument("--dataset", help="dataset name (default: from the job's config.json)")
    p.add_argument("--arm", help="arm name (default: the agent name)")
    p.add_argument("--channels", action="store_true",
                   help="handoff tasks: split '<task>--<channel>' into task and arm")
    p.add_argument("--merge", action="store_true", help="the jobs are parts of one run: write one run file")
    p.set_defaults(fn=_import_harbor)

    p = sub.add_parser("import-reports",
                       help="convert a Scholion Cloud reports export (one repo, one week) into a ledger run")
    p.add_argument("reports", help="the JSON of GET /v1/ee/reports?repo=R&from=<Monday>&to=<Sunday>")
    p.add_argument("--repo", help="the export's repo (checked against it)")
    p.add_argument("--week", help="YYYY-MM-DD, the Monday the export covers (checked against it)")
    p.add_argument("--arm", action="append", metavar="OWNER=ARM",
                   help="the path (teams or autopilot) of a task owner the default table does not name")
    p.add_argument("--revision", type=int, help="supersede a published week (2, 3, ...); needs --notes")
    p.add_argument("--notes", help="why this run supersedes the week")
    p.add_argument("--out", default=str(REPO / "runs"))
    p.set_defaults(fn=_import_reports)

    p = sub.add_parser("freeze", help="freeze a handoff predecessor job: one frozen A per task")
    p.add_argument("job", help="the Harbor job directory of the A run")
    p.add_argument("--out", default=str(REPO / "datasets" / "_shared" / "handoff" / "interrupt"))
    p.add_argument("--cut-turns", type=int, required=True, help="the pre-registered max_turns A ran with")
    p.set_defaults(fn=_freeze)

    p = sub.add_parser("rewards", help="dataset validation: exit 1 unless every trial scored --expect (nop 0, oracle 1)")
    p.add_argument("job")
    p.add_argument("--expect", type=float, required=True)
    p.set_defaults(fn=_rewards)

    p = sub.add_parser("stats", help="per-arm summary, or paired deltas with --paired BASE ARM[:arm]...")
    p.add_argument("files", nargs="*")
    p.add_argument("--paired", nargs="+", metavar="RUNFILE")
    p.set_defaults(fn=_stats)

    p = sub.add_parser("detect", help="set change flags on every run against its series' history")
    p.add_argument("runs", nargs="?", default=str(REPO / "runs"))
    p.set_defaults(fn=_detect)

    p = sub.add_parser("site", help="build site/data from runs/")
    p.add_argument("--runs", default=str(REPO / "runs"))
    p.add_argument("--out", default=str(REPO / "site" / "data"))
    p.add_argument("--check", action="store_true", help="fail if site/data is stale")
    p.set_defaults(fn=_site)

    p = sub.add_parser("budget", help="sum spend over Harbor job dirs; exit 1 when spend + reserve > cap")
    p.add_argument("jobs")
    p.add_argument("--cap", type=float)
    p.add_argument("--reserve", type=float, default=0.0)
    p.set_defaults(fn=_budget)

    p = sub.add_parser("tiers", help="per-tier tables (datasets/tiers.toml) of a pre-registered comparison")
    p.add_argument("--runs", default=str(REPO / "runs"))
    p.add_argument("--prereg", help="include the runs whose prereg is this path")
    p.add_argument("--also", nargs="+", metavar="RUNFILE", help="run files to include as well (reused data)")
    p.set_defaults(fn=_tiers)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
