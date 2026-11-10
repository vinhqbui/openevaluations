"""`oe tiers`: one table per difficulty tier, one row per model, never pooled across tiers."""

from oe import runfile
from oe.cli import main
from oe.tiers import tier_tables


def _run(rid, dataset, model, prereg, sessions):
    run = {"type": "run", "id": rid, "date": "2026-11-10T00:00:00Z", "dataset": {"name": dataset}, "model": {"provider": "deepseek", "name": model},
           "agent": {"name": "claude-code", "version": "2.1.318"}, "prereg": prereg}
    ss = [{"type": "session", "run_id": rid, "task": t, "arm": "cold", "attempt": 1, "status": st,
           "accepted": acc, "cost_usd": cost, "cost_source": "estimated", "turns": turns}
          for t, st, acc, cost, turns in sessions]
    return run, ss


def _write(tmp_path):
    runs = tmp_path / "runs"
    p = "docs/PREREG-tracker-tiers.md"
    for rid, ds, model, prereg, ss in [
        ("a", "tallyho-hard", "deepseek-v4-pro", p, [("x", "ok", True, 0.10, 20), ("y", "ok", False, 0.20, 40),
                                                    ("z", "error", False, 0.05, None)]),
        ("b", "tallyho-hard", "deepseek-v4-pro", p, [("x", "ok", True, 0.10, 30)]),
        ("c", "tallyho-hard", "deepseek-flash", p, [("x", "ok", False, 0.03, 40)]),
        ("d", "tallyho-cold", "deepseek-flash", None, [("e", "ok", True, 0.01, 9)]),
        ("e", "tallyho-cold", "deepseek-flash", None, [("e", "ok", True, 0.02, 11)]),
        ("f", "tallyho-more", "deepseek-v4-pro", p, [("m", "ok", True, 0.04, 12)]),
    ]:
        runfile.write(runs / f"{rid}.jsonl", *_run(rid, ds, model, prereg, ss))
    return runs


def test_tables_are_per_tier_and_model_and_count_errors_and_their_spend(tmp_path):
    runs = _write(tmp_path)
    picked = [runfile.read(runs / f"{r}.jsonl") for r in "abcdf"]
    tables = tier_tables(picked, {"tallyho-cold": "easy", "tallyho-more": "easy", "tallyho-hard": "hard"})
    assert list(tables) == ["easy", "hard"]
    hard = {r["model"]: r for r in tables["hard"]}
    pro = hard["deepseek-v4-pro"]
    assert (pro["n"], pro["solved"], pro["errors"]) == (3, 2, 1)
    assert pro["rate"] == 2 / 3
    assert abs(pro["cost_per_solved"] - 0.40 / 2) < 1e-12  # valid sessions' spend over solved
    assert abs(pro["spent"] - 0.45) < 1e-12               # the errored session's cost still counts here
    assert pro["median_turns"] == 30
    assert pro["datasets"] == ["tallyho-hard"] and pro["tasks"] == 2
    flash = hard["deepseek-flash"]
    assert flash["solved"] == 0 and flash["cost_per_solved"] is None
    easy = {r["model"]: r for r in tables["easy"]}
    assert easy["deepseek-flash"]["n"] == 1 and easy["deepseek-v4-pro"]["datasets"] == ["tallyho-more"]


def test_cli_selects_the_preregistered_runs_plus_named_ones(tmp_path, capsys):
    runs = _write(tmp_path)
    assert main(["tiers", "--runs", str(runs), "--prereg", "docs/PREREG-tracker-tiers.md",
                 "--also", str(runs / "d.jsonl")]) == 0
    out = capsys.readouterr().out
    assert out.index("## easy") < out.index("## hard")
    assert "| deepseek-v4-pro | 3 | 2 | 67% [21%, 94%] | 1 | $0.2000 | 30 | $0.4500 |" in out
    assert "| deepseek-flash | 1 | 0 | 0% [0%, 79%] | 0 | - | 40 | $0.0300 |" in out
    assert "| deepseek-flash | 1 | 1 | 100% [21%, 100%] | 0 | $0.0100 | 9 | $0.0100 |" in out  # d, not e
    assert "estimated" in out and "no significance" in out
