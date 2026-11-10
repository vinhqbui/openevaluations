"""Per-tier tables (datasets/tiers.toml): one row per model, never pooled across tiers."""

import tomllib

from . import REPO, stats

TIERS = REPO / "datasets" / "tiers.toml"


def load_tiers(path=TIERS):
    return tomllib.loads(path.read_text(encoding="utf-8"))["tiers"]


def tier_tables(runs, tiers):
    """{tier: [row per model]} over (run, sessions) pairs; runs of datasets without a tier are skipped."""
    cells = {}
    for run, sessions in runs:
        tier = tiers.get(run["dataset"]["name"])
        if tier is None:
            continue
        cell = cells.setdefault((tier, run["model"]["name"]), {"sessions": [], "datasets": set()})
        cell["sessions"] += sessions
        cell["datasets"].add(run["dataset"]["name"])
    out = {}
    for (tier, model), cell in sorted(cells.items()):
        ss = cell["sessions"]
        s = stats.summary(ss)
        out.setdefault(tier, []).append({
            "model": model, "n": s["n"], "solved": s["accepted"], "rate": s["rate"], "wilson": s["wilson"],
            "errors": s["invalid"], "cost_per_solved": s["cost_per_accepted"],
            "median_turns": s["median_turns"], "spent": sum(x.get("cost_usd") or 0 for x in ss),
            "datasets": sorted(cell["datasets"]), "tasks": len({x["task"] for x in stats.valid(ss)}),
            "cost_sources": sorted({x.get("cost_source") for x in ss}),
        })
    return out


def _pct(x):
    return "-" if x is None else f"{x:.0%}"


def markdown(tables):
    lines = []
    for tier, rows in tables.items():
        lines += [f"## {tier}", "",
                  "| model | n | solved | solved rate [Wilson 95%] | errors | cost per solved | median turns | spent |",
                  "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            cps = "-" if r["cost_per_solved"] is None else f"${r['cost_per_solved']:.4f}"
            turns = "-" if r["median_turns"] is None else f"{r['median_turns']:g}"
            lines.append(f"| {r['model']} | {r['n']} | {r['solved']} | {_pct(r['rate'])} "
                         f"[{_pct(r['wilson'][0])}, {_pct(r['wilson'][1])}] | {r['errors']} | {cps} | {turns} "
                         f"| ${r['spent']:.4f} |")
        lines += ["", "Datasets: " + "; ".join(f"{r['model']}: {', '.join(r['datasets'])} ({r['tasks']} tasks)"
                                              for r in rows),
                  "Costs: " + ", ".join(sorted({c for r in rows for c in r["cost_sources"]})) +
                  ". n counts valid sessions; errors are not in n, but their cost is in spent.", ""]
    lines.append("Every cell has fewer than 30 valid sessions: descriptive only, no significance claimed."
                 if all(r["n"] < stats.NO_CLAIM_BELOW for rows in tables.values() for r in rows)
                 else "Cells below 30 valid sessions are descriptive only, no significance claimed.")
    return "\n".join(lines) + "\n"
