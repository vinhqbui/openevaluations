import json
from pathlib import Path

import pytest

from oe import stats
from oe.import_scholion import convert_dir

FIX = Path(__file__).parent / "fixtures"


def sessions(rows_name, meta_name="base-meta.json"):
    import shutil, tempfile

    d = Path(tempfile.mkdtemp())
    shutil.copy(FIX / rows_name, d / "rows.jsonl")
    shutil.copy(FIX / meta_name, d / "meta.json")
    run, ss = convert_dir(d, run_id="t")
    return ss


def test_wilson_known_values():
    assert stats.wilson(0, 10)[0] == 0.0
    assert stats.wilson(10, 10)[1] == pytest.approx(1.0)
    lo, hi = stats.wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-4)
    assert hi == pytest.approx(0.7634, abs=1e-4)
    assert stats.wilson(0, 0) == (0.0, 1.0)


def test_bootstrap_ci_is_seeded_and_brackets_the_median():
    v = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    a = stats.bootstrap_ci(v, seed=1)
    assert a == stats.bootstrap_ci(v, seed=1)
    assert a[0] <= stats.median(v) <= a[1]


def test_paired_report_reproduces_the_published_haiku_numbers():
    # bench/results/2026-10-27-haiku/paired.py on the 04-final-shipped runs printed:
    # cost +0.0% [-3.9, +4.2], tokens +5.9% [+2.5, +9.4], turns -12.9% [-18.3, -7.0], wall -2.3% [-7.4, +3.3]
    rep = stats.paired_report(sessions("base-rows.jsonl"), sessions("av-rows.jsonl"))
    r = {k: tuple(round(x * 100, 1) for x in v) for k, v in rep.items()}
    assert r["cost"] == (0.0, -3.9, 4.2)
    assert r["tokens"] == (5.9, 2.5, 9.4)
    assert r["turns"] == (-12.9, -18.3, -7.0)
    assert r["wall"] == (-2.3, -7.4, 3.3)


def _run(i, accepted, n=12, tool_calls=8, flags=None):
    return {
        "run": {"id": f"r{i}", "date": f"2026-11-{i + 1:02d}T00:00:00Z", "flags": flags or []},
        "sessions": [
            {"status": "ok", "accepted": k < accepted, "tool_calls": tool_calls} for k in range(n)
        ],
    }


def test_detect_change_flags_degraded_then_recovered():
    hist = [_run(i, 11) for i in range(4)]
    bad = _run(4, 3)
    assert "degraded" in stats.detect_change(bad, hist)
    worse_tools = _run(4, 11, tool_calls=20)
    assert "tool_calls_up" in stats.detect_change(worse_tools, hist)
    prev = _run(4, 3, flags=["degraded"])
    good = _run(5, 11)
    assert stats.detect_change(good, hist[1:] + [prev]) == ["recovered"]


def test_detect_change_low_n_sets_nothing_else():
    hist = [_run(i, 11) for i in range(4)]
    assert stats.detect_change(_run(4, 0, n=5), hist) == ["low_n"]


def test_detect_change_without_history_is_empty():
    assert stats.detect_change(_run(0, 5), []) == []
