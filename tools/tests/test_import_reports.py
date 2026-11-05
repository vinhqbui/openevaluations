"""The ledger: `oe import-reports` (a Scholion Cloud reports export -> runs/<week>-ledger-<repo>.jsonl),
its validate rule, and its place on the site (its own ledger.json, never a tracker series)."""

import copy
import json
from pathlib import Path

import pytest

from oe import runfile, schema, site
from oe.cli import main
from oe.import_reports import LedgerError, convert, import_file

FIX = Path(__file__).parent / "fixtures"
REPORT = FIX / "reports-scholion-2026-11-02.json"


def report():
    return json.loads(REPORT.read_text(encoding="utf-8"))


def write(tmp_path, rep, name="reports.json"):
    p = tmp_path / name
    p.write_text(json.dumps(rep), encoding="utf-8")
    return p


def test_one_session_per_merged_feature_with_the_plan_mapping():
    run, ss = convert(report())
    assert run["id"] == "2026-11-02-ledger-scholion"
    assert run["date"] == "2026-11-02T00:00:00Z"
    assert run["harness"]["runner"] == "scholion-cloud"
    assert run["dataset"] == {"name": "scholion-dev", "version": None, "rev": None, "visibility": "public"}
    assert run["config"]["arm"] == "multi" and run["config"]["arms"] == ["autopilot", "teams"]
    assert run["prereg"] == "docs/PREREG-ledger.md"
    assert [s["task"] for s in ss] == [
        "trunk-advance-after-merge", "lease-renewal-on-request-changes",
        "attention-lists-stale-reviews", "digest-names-the-repo",
    ]
    assert [s["arm"] for s in ss] == ["teams", "teams", "autopilot", "teams"]
    for s in ss:
        assert s["status"] == "ok" and s["accepted"] is True and s["reward"] == 1.0
        assert s["cost_source"] == "measured"
    assert [s["cost_usd"] for s in ss] == [1.84213, 2.513377, 0.031906, 0.402118]
    # backlog to merge; a task that did not come from the backlog falls back to task-to-merge
    assert [s["wall_secs"] for s in ss] == [23400.0, 97200.0, 130500.0, 13500.0]
    assert ss[3]["reason"] and "backlog" in ss[3]["reason"]
    # a feature re-merged after a revert is its second attempt
    assert [s["attempt"] for s in ss] == [1, 1, 2, 1]
    # interventions on each feature in the week (the escalation is on a task that did not merge)
    assert [s["interventions"] for s in ss] == [1, 2, 1, 1]
    assert [s["unpriced_tokens"] for s in ss] == [0, 0, 0, 1200]


def test_the_week_figures_are_the_daemons_summary_without_names():
    run, _ = convert(report())
    lg = run["ledger"]
    assert lg["repo"] == "scholion"
    assert lg["from"] == "2026-11-02T00:00:00Z" and lg["to"] == "2026-11-09T00:00:00Z"
    assert lg["features_merged"] == 4
    assert lg["cost_per_merged_feature_usd"] == 1.197383
    assert lg["human_interventions"] == 6 and lg["escalations"] == 1 and lg["gate_decisions"] == 5
    assert lg["reverts"] == 1 and lg["unpriced_tokens"] == 1200
    assert lg["backlog_to_merge_median_secs"] == 97200.0
    assert lg["review_latency_median_secs"] == 1320.0
    assert lg["gate_wait_median_secs"] == 2880.0
    assert lg["review_rounds_mean"] == 0.25
    assert lg["owners"] == {"builder": "autopilot", "fable-opus": "teams"}
    assert lg["models"] == ["claude-opus-5-5", "claude-sonnet-5-5", "deepseek-flash"]
    assert lg["runner_outcomes"][0] == {"outcome": "escalated", "sessions": 1, "mean_wall_secs": 1804.0,
                                        "check_failed": 1}
    assert lg["memory_signal"] == {"records_written": 23, "pack_tokens": 9412, "pack_items": 61, "known_findings": 1}
    assert run["model"] == {"provider": "multi", "name": "multi"}


@pytest.mark.parametrize("repo", ["scholion", "agentvcs"])
def test_no_title_actor_or_comment_is_ever_published(tmp_path, repo):
    rep = report()
    text = json.dumps(rep).replace('"scholion"', json.dumps(repo))
    rep = json.loads(text)
    p = import_file(write(tmp_path, rep), tmp_path / "runs")
    out = p.read_text(encoding="utf-8")
    titles = {row["title"] for sec in ("features", "interventions", "reverts") for row in rep[sec]}
    for leak in titles | {"owner@example.com", "Renew the lease", "secret plan", "Loop noise",
                          "0b6c5f1e-3a51-4a8e-9d55-1f1c2b7a9e01"}:
        assert leak not in out, leak
    assert p.name == f"2026-11-02-ledger-{repo}.jsonl"
    assert schema.validate_file(p) == []


def test_import_writes_a_valid_file_and_never_overwrites_one(tmp_path):
    src = write(tmp_path, report())
    p = import_file(src, tmp_path / "runs")
    assert p.name == "2026-11-02-ledger-scholion.jsonl"
    assert schema.validate_file(p) == []
    run, ss = runfile.read(p)
    assert run["ledger"]["features_merged"] == len(ss) == 4
    with pytest.raises(LedgerError, match="exists"):
        import_file(src, tmp_path / "runs")


def test_cli_import_reports(tmp_path, capsys):
    src = write(tmp_path, report())
    assert main(["import-reports", str(src), "--repo", "scholion", "--week", "2026-11-02",
                 "--out", str(tmp_path / "runs")]) == 0
    assert "2026-11-02-ledger-scholion.jsonl" in capsys.readouterr().out
    assert main(["validate", str(tmp_path / "runs")]) == 0


def test_the_export_must_be_one_repo_and_one_monday_to_monday_week():
    with pytest.raises(LedgerError, match="repo"):
        convert(report(), repo="agentvcs")
    rep = report()
    rep["repo"] = None
    with pytest.raises(LedgerError, match="repo"):
        convert(rep)
    with pytest.raises(LedgerError, match="week"):
        convert(report(), week="2026-11-09")
    rep = report()
    rep["from"], rep["to"] = "2026-11-03T00:00:00Z", "2026-11-10T00:00:00Z"
    with pytest.raises(LedgerError, match="Monday"):
        convert(rep)
    rep = report()
    rep["to"] = "2026-11-08T00:00:00Z"
    with pytest.raises(LedgerError, match="week"):
        convert(rep)
    rep = report()
    rep["from"] = rep["to"] = None
    with pytest.raises(LedgerError, match="week"):
        convert(rep, week="2026-11-02")


def test_an_unmapped_owner_is_refused_not_guessed():
    rep = report()
    rep["features"][0]["owner"] = "grok"
    with pytest.raises(LedgerError, match="grok"):
        convert(rep)
    run, ss = convert(rep, arms={"grok": "teams"})
    assert ss[0]["arm"] == "teams"
    with pytest.raises(LedgerError, match="teams or autopilot"):
        convert(rep, arms={"grok": "solo"})


def test_a_single_model_and_a_single_arm():
    rep = report()
    rep["features"] = [rep["features"][2]]
    rep["summary"]["features_merged"] = 1
    run, ss = convert(rep)
    assert run["model"] == {"provider": "deepseek", "name": "deepseek-flash"}
    assert run["config"]["arm"] == "autopilot" and run["config"]["arms"] == ["autopilot"]


def test_an_empty_week_is_a_run_with_no_sessions(tmp_path):
    rep = report()
    rep["features"] = []
    rep["summary"]["features_merged"] = 0
    rep["summary"]["cost_per_merged_feature_usd"] = None
    p = import_file(write(tmp_path, rep), tmp_path / "runs")
    assert schema.validate_file(p) == []
    run, ss = runfile.read(p)
    assert ss == [] and run["config"]["arms"] == []


def test_a_daemon_before_plan_15_has_no_review_flow_figures():
    rep = report()
    for k in ("review_latency", "gate_wait", "review_rounds", "memory_signal"):
        del rep["summary"][k]
    del rep["runner_outcomes"]
    run, _ = convert(rep)
    lg = run["ledger"]
    assert lg["review_latency_median_secs"] is None and lg["gate_wait_median_secs"] is None
    assert lg["review_rounds_mean"] is None and lg["memory_signal"] is None
    assert lg["runner_outcomes"] == []


# --- the validate rule -------------------------------------------------------------------------

def _broken(tmp_path, change):
    run, ss = convert(report())
    run, ss = copy.deepcopy(run), copy.deepcopy(ss)
    change(run, ss)
    p = tmp_path / f"{run['id']}.jsonl"
    runfile.write(p, run, ss)
    return schema.validate_file(p)


@pytest.mark.parametrize("change, needle", [
    (lambda r, s: r["dataset"].update(name="tallyho-cold"), "scholion-dev"),
    (lambda r, s: s[0].update(arm="cold"), "teams"),
    (lambda r, s: s[0].update(accepted=False, reward=0.0), "merged"),
    (lambda r, s: s[0].update(cost_source="estimated"), "measured"),
    (lambda r, s: s[0].update(cost_usd=None), "measured"),
    (lambda r, s: s[0].update(task="Trunk advance after merge"), "slug"),
    (lambda r, s: s.pop(), "features_merged"),
    (lambda r, s: r.pop("ledger"), "ledger"),
    (lambda r, s: r["dataset"].update(visibility="private"), "public"),
    (lambda r, s: r["ledger"].update(repo="agentvcs"), "repo"),
])
def test_validate_rule_for_ledger_runs(tmp_path, change, needle):
    errs = _broken(tmp_path, change)
    assert any(needle in e for e in errs), errs


def test_validate_rule_ledger_file_name_is_week_and_repo(tmp_path):
    run, ss = convert(report())
    p = tmp_path / "ledger-scholion.jsonl"
    run["id"] = "ledger-scholion"
    runfile.write(p, run, ss)
    assert any("ledger" in e and "<week>" in e for e in schema.validate_file(p))
    run["id"] = "2026-11-03-ledger-scholion"
    run["date"] = "2026-11-03T00:00:00Z"
    p = tmp_path / "2026-11-03-ledger-scholion.jsonl"
    runfile.write(p, run, ss)
    assert any("Monday" in e for e in schema.validate_file(p))


def test_only_a_ledger_run_carries_a_ledger(tmp_path):
    run, ss = convert(report())
    run["harness"]["runner"] = "harbor"
    p = tmp_path / f"{run['id']}.jsonl"
    runfile.write(p, run, ss)
    assert any("ledger" in e for e in schema.validate_file(p))


# --- the site --------------------------------------------------------------------------------

def _tracker_run(tmp_path):
    from oe import runfile as rf
    run = {"type": "run", "schema_version": "oe/1", "id": "2026-11-02-tallyho-cold-x", "date": "2026-11-02T10:00:00Z",
           "dataset": {"name": "tallyho-cold", "visibility": "public"},
           "agent": {"name": "claude-code", "version": "2.1.316"}, "model": {"provider": "deepseek", "name": "deepseek-flash"},
           "config": {"arm": "cold"}, "harness": {"runner": "harbor"}, "machine": {"kind": "local"}, "flags": []}
    s = {"type": "session", "run_id": run["id"], "task": "csv-escaping", "arm": "cold", "attempt": 1, "status": "ok",
         "reward": 1.0, "accepted": True, "cost_usd": 0.01, "cost_source": "measured", "wall_secs": 60.0, "truncated": False}
    rf.write(tmp_path / "runs" / f"{run['id']}.jsonl", run, [s])


def test_site_puts_the_ledger_on_its_own_page_never_in_the_tracker(tmp_path):
    runs = tmp_path / "runs"
    import_file(write(tmp_path, report()), runs)
    rep = report()
    for f in rep["features"]:
        f["merged_at"] = f["merged_at"].replace("2026-11-0", "2026-11-1")
    rep["from"], rep["to"] = "2026-11-09T00:00:00Z", "2026-11-16T00:00:00Z"
    rep["features"] = rep["features"][:2]
    rep["summary"]["features_merged"] = 2
    import_file(write(tmp_path, rep, "w2.json"), runs)
    _tracker_run(tmp_path)
    out = site.build(runs, tmp_path / "data")

    tracker = json.loads((out / "tracker.json").read_text(encoding="utf-8"))
    assert [s["dataset"] for s in tracker["series"]] == ["tallyho-cold"]
    datasets = json.loads((out / "datasets.json").read_text(encoding="utf-8"))
    assert list(datasets["datasets"]) == ["tallyho-cold"]
    index = json.loads((out / "runs.json").read_text(encoding="utf-8"))
    assert {r["runner"] for r in index["runs"]} == {"harbor", "scholion-cloud"}
    assert (out / "runs" / "2026-11-02-ledger-scholion.jsonl").exists()

    ledger = json.loads((out / "ledger.json").read_text(encoding="utf-8"))
    (repo,) = ledger["repos"]
    assert repo["repo"] == "scholion"
    w1, w2 = repo["weeks"]
    assert w1["week"] == "2026-11-02" and w2["week"] == "2026-11-09"
    assert w1["n"] == 4 and w1["arms"]["teams"]["n"] == 3 and w1["arms"]["autopilot"]["n"] == 1
    assert w1["cost_per_merged_feature_usd"] == pytest.approx(4.789531 / 4)
    assert w1["interventions_per_feature"] == pytest.approx(5 / 4)
    assert w1["partial_cost_features"] == 1
    assert w1["arms"]["autopilot"]["cost_per_merged_feature_usd"] == pytest.approx(0.031906)
    assert w1["reverts"] == 1 and w1["human_interventions"] == 6
    assert w1["raw"] == "/data/runs/2026-11-02-ledger-scholion.jsonl"
    assert w2["n"] == 2


def test_site_ledger_is_empty_without_ledger_runs(tmp_path):
    _tracker_run(tmp_path)
    out = site.build(tmp_path / "runs", tmp_path / "data")
    assert json.loads((out / "ledger.json").read_text(encoding="utf-8")) == {"repos": []}


def test_detect_leaves_ledger_runs_alone(tmp_path):
    runs = tmp_path / "runs"
    p = import_file(write(tmp_path, report()), runs)
    before = p.read_bytes()
    assert main(["detect", str(runs)]) == 0
    assert p.read_bytes() == before


def test_a_revision_supersedes_its_week_on_the_site(tmp_path):
    runs = tmp_path / "runs"
    src = write(tmp_path, report())
    import_file(src, runs)
    with pytest.raises(LedgerError, match="notes"):
        import_file(src, runs, revision=2)
    rep = report()
    rep["features"][0]["cost_usd"] = 1.5
    p = import_file(write(tmp_path, rep, "r2.json"), runs, revision=2, notes="re-exported after a price fix")
    assert p.name == "2026-11-02-ledger-scholion.2.jsonl"
    assert schema.validate_file(p) == []
    out = site.build(runs, tmp_path / "data")
    (repo,) = json.loads((out / "ledger.json").read_text(encoding="utf-8"))["repos"]
    (week,) = repo["weeks"]
    assert week["revision"] == 2 and week["notes"] == "re-exported after a price fix"
    assert week["cost_per_merged_feature_usd"] == pytest.approx((1.5 + 2.513377 + 0.031906 + 0.402118) / 4)
