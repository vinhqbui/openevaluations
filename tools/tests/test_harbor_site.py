import json
import shutil
from pathlib import Path

from oe import runfile, schema, site
from oe.budget import spent
from oe.cli import main
from oe.import_harbor import import_job

FIX = Path(__file__).parent / "fixtures"


def fake_job(tmp_path, n=3):
    job = tmp_path / "jobs" / "tracker-tallyho-claude-code"
    for i in range(n):
        t = job / f"compound-discounts__{i}"
        (t / "agent").mkdir(parents=True)
        (t / "result.json").write_text(json.dumps({
            "task_name": "compound-discounts", "trial_name": t.name,
            "agent_info": {"name": "claude-code", "version": "2.1.320",
                           "model_info": {"name": "claude-haiku-5-5", "provider": "anthropic"}},
            "agent_result": {"n_input_tokens": 12000, "n_cache_tokens": 8000, "n_output_tokens": 900,
                             "cost_usd": None if i == 2 else 0.01, "metadata": {}},
            "verifier_result": {"rewards": {"reward": 1 if i else 0}},
            "exception_info": None,
            "started_at": f"2026-11-02T05:0{i}:00Z",
            "agent_execution": {"started_at": f"2026-11-02T05:0{i}:00Z", "finished_at": f"2026-11-02T05:0{i}:30Z"},
        }))
        (t / "agent" / "trajectory.json").write_text(json.dumps({
            "schema_version": "ATIF-v1.8",
            "agent": {"name": "claude-code", "version": "2.1.320", "model_name": "claude-haiku-5-5"},
            "steps": [
                {"step_id": 1, "source": "user", "message": "goal"},
                {"step_id": 2, "source": "agent", "message": "", "tool_calls": [
                    {"tool_call_id": "a", "function_name": "Edit",
                     "arguments": {"file_path": "/app/tallyho/pricing/quote.py", "new_string": "x.times(1 / n)"}}]},
                {"step_id": 3, "source": "agent", "message": "done"},
            ],
        }))
        (t / "agent" / "claude-code.txt").write_text('{"type":"result","num_turns":3}\n')
    (job / "oe-env.json").write_text(json.dumps({"dataset": "tallyho-cold", "harbor_version": "0.20.0", "attempts": n}))
    return job


def test_import_harbor_job_is_valid_and_maps_fields(tmp_path):
    p = import_job(fake_job(tmp_path), tmp_path / "runs")
    assert schema.validate_file(p) == []
    run, ss = runfile.read(p)
    assert run["agent"] == {"name": "claude-code", "version": "2.1.320"}
    assert run["dataset"]["name"] == "tallyho-cold"
    assert [s["attempt"] for s in ss] == [1, 2, 3]
    assert [s["accepted"] for s in ss] == [False, True, True]
    s = ss[0]
    assert s["tokens"] == {"input": 4000, "output": 900, "cache_read": 8000, "cache_write": None}
    assert s["llm_calls"] == 2 and s["tool_calls"] == 1 and s["wall_secs"] == 30.0
    assert s["truncated"] is False and s["trajectory"]["kind"] == "atif"
    assert s["turns"] == 3  # Claude Code's own num_turns, from its result line
    assert ss[2]["cost_source"] == "unavailable"


def test_budget_sums_costs_and_estimates_missing_ones(tmp_path):
    total, unpriced = spent(fake_job(tmp_path))
    # two measured 0.01 + one estimate at Haiku 5.5 prices: 4000*0.1 + 8000*0.01 + 900*0.5 = 930 -> 0.00093
    assert unpriced == 0
    assert abs(total - 0.02093) < 1e-9
    assert main(["budget", str(tmp_path / "jobs"), "--cap", "0.03", "--reserve", "0.01"]) == 1
    assert main(["budget", str(tmp_path / "jobs"), "--cap", "1"]) == 0


def test_site_build_is_deterministic_and_check_detects_staleness(tmp_path):
    runs = tmp_path / "runs"
    import_job(fake_job(tmp_path), runs)
    out = tmp_path / "data"
    site.build(runs, out)
    assert site.check(runs, out) == []
    tracker = json.loads((out / "tracker.json").read_text())
    (sr,) = tracker["series"]
    point = sr["arms"]["claude-code"][0]
    assert point["agent_version"] == "2.1.320" and point["accepted"] == 2 and point["n"] == 3
    assert (out / "runs" / next(runs.glob("*.jsonl")).name).exists()
    (out / "runs.json").write_text("{}")
    assert site.check(runs, out) == ["stale: runs.json"]


def test_non_claude_models_are_repriced_and_marked_estimated(tmp_path):
    # Claude Code prices unknown models at a Claude list-price fallback (costBasis "unknown");
    # for DeepSeek through its Anthropic-compatible API that is ~20x too high.
    job = fake_job(tmp_path, n=1)
    res = job / "compound-discounts__0" / "result.json"
    r = json.loads(res.read_text())
    r["agent_info"]["model_info"] = {"name": "deepseek-flash", "provider": "anthropic"}
    r["agent_result"].update(n_input_tokens=142322, n_cache_tokens=125056, n_output_tokens=3211, cost_usd=0.229133)
    res.write_text(json.dumps(r))
    run, (s,) = runfile.read(import_job(job, tmp_path / "runs"))
    assert run["model"] == {"provider": "deepseek", "name": "deepseek-flash"}
    assert s["cost_source"] == "estimated"
    # 17266 * 0.30 + 125056 * 0.006 + 3211 * 1.20, per million
    assert abs(s["cost_usd"] - 0.009783336) < 1e-9


def test_codex_reports_no_cost_so_its_tokens_are_priced_and_marked_estimated(tmp_path):
    # Harbor's codex agent leaves cost_usd None without litellm; the 2026-11-04 smoke trial's usage
    job = fake_job(tmp_path, n=1)
    res = job / "compound-discounts__0" / "result.json"
    r = json.loads(res.read_text())
    r["agent_info"] = {"name": "codex", "version": "0.166.0",
                       "model_info": {"name": "deepseek-flash", "provider": "deepseek"}}
    r["agent_result"].update(n_input_tokens=228166, n_cache_tokens=209280, n_output_tokens=9416, cost_usd=None)
    res.write_text(json.dumps(r))
    run, (s,) = runfile.read(import_job(job, tmp_path / "runs"))
    assert run["agent"] == {"name": "codex", "version": "0.166.0"}
    assert run["model"] == {"provider": "deepseek", "name": "deepseek-flash"}
    assert s["cost_source"] == "estimated"
    # 18886 * 0.30 + 209280 * 0.006 + 9416 * 1.20, per million
    assert abs(s["cost_usd"] - 0.01822068) < 1e-9
    assert spent(job) == (s["cost_usd"], 0)


def _deepseek(job):
    for res in job.glob("*/result.json"):
        r = json.loads(res.read_text())
        r["agent_info"]["model_info"] = {"name": "deepseek-flash", "provider": "anthropic"}
        r["agent_result"].update(n_input_tokens=142322, n_cache_tokens=125056, n_output_tokens=3211, cost_usd=0.229133)
        res.write_text(json.dumps(r))
    return job


def test_budget_reprices_claude_code_on_a_non_claude_model(tmp_path):
    # the CLI's own figure is ~20x the real DeepSeek price, so a $10 cap would stop at ~$0.50
    total, unpriced = spent(_deepseek(fake_job(tmp_path, n=2)))
    assert unpriced == 0 and abs(total - 2 * 0.009783336) < 1e-9


def test_av_arm_import_names_the_arm_and_marks_invalid_sessions(tmp_path):
    job = fake_job(tmp_path)
    res = job / "compound-discounts__1" / "result.json"
    r = json.loads(res.read_text())
    r["agent_result"]["metadata"] = {"oe_invalid": "the av hooks never fired", "av_hook_counts": {}}
    res.write_text(json.dumps(r))
    run, ss = runfile.read(import_job(job, tmp_path / "runs", arm="av"))
    assert run["config"]["arm"] == "av" and "-claude-code-av-" in run["id"]
    assert run["harness"]["scholion_rev"] is None  # set from oe-env.json on the av leg
    assert {s["arm"] for s in ss} == {"av"}
    bad = ss[1]
    assert bad["status"] == "invalid" and bad["accepted"] is False and bad["reason"] == "the av hooks never fired"


def test_tracker_pairs_an_arm_with_the_same_days_cold_run(tmp_path):
    runs = tmp_path / "runs"
    a, b = tmp_path / "a", tmp_path / "b"
    import_job(fake_job(a), runs, arm="cold")
    av = fake_job(b)
    for res in av.glob("*/result.json"):  # same tasks, half the tokens
        r = json.loads(res.read_text())
        r["agent_result"].update(n_input_tokens=6000, n_cache_tokens=4000, n_output_tokens=450, cost_usd=0.005)
        r["trial_name"] += "-av"
        res.write_text(json.dumps(r))
    import_job(av, runs, arm="av")
    site.build(runs, tmp_path / "data")
    (sr,) = json.loads((tmp_path / "data" / "tracker.json").read_text())["series"]
    assert set(sr["arms"]) == {"cold", "av"}
    (cold,), (avp,) = sr["arms"]["cold"], sr["arms"]["av"]
    assert "vs_cold" not in cold
    assert avp["vs_cold"]["cost"][0] < 0 and avp["vs_cold"]["cold_run_id"] == cold["run_id"]


def test_tracker_pairing_never_crosses_into_another_runs_cold_arm(tmp_path):
    runs = tmp_path / "runs"
    cold_only = import_job(fake_job(tmp_path / "a"), runs, arm="cold")
    # a multi-arm run on the same day (like scholion-bench's): its notes arm pairs with its own cold
    run, ss = runfile.read(cold_only)
    run = dict(run, id=run["id"] + "-multi", config=dict(run["config"], arm="multi", arms=["cold", "notes"]))
    multi = [dict(s, run_id=run["id"]) for s in ss] + [dict(s, run_id=run["id"], arm="notes") for s in ss]
    runfile.write(runs / f"{run['id']}.jsonl", run, multi)
    # two cold-only runs that day: an av run without a source of its own is ambiguous, so unpaired
    other = fake_job(tmp_path / "b")
    for res in other.glob("*/result.json"):  # distinct trial names, so a distinct run id
        r = json.loads(res.read_text())
        r["trial_name"] += "-b"
        res.write_text(json.dumps(r))
    import_job(other, runs, arm="cold")
    av = fake_job(tmp_path / "c")
    for res in av.glob("*/result.json"):
        r = json.loads(res.read_text())
        r["trial_name"] += "-av"
        res.write_text(json.dumps(r))
    import_job(av, runs, arm="av")
    site.build(runs, tmp_path / "data")
    (sr,) = json.loads((tmp_path / "data" / "tracker.json").read_text())["series"]
    (notes,) = sr["arms"]["notes"]
    assert notes["vs_cold"]["cold_run_id"] == run["id"]
    (avp,) = sr["arms"]["av"]
    assert "vs_cold" not in avp


def test_run_agent_version_skips_trials_that_failed_setup(tmp_path):
    job = fake_job(tmp_path)
    first = sorted(job.glob("*/result.json"))[0]
    r = json.loads(first.read_text())
    r["agent_info"]["version"] = "unknown"
    first.write_text(json.dumps(r))
    run, _ = runfile.read(import_job(job, tmp_path / "runs"))
    assert run["agent"]["version"] == "2.1.320"


def test_deepseek_v4_pro_is_priced_at_its_peak_list_rate(tmp_path):
    # api-docs.deepseek.com/quick_start/pricing, checked 2026-11-10: deepseek-v4-pro peak rates
    # $1.32 input (cache miss), $0.044 cache hit, $3.96 output per million tokens
    job = fake_job(tmp_path, n=1)
    res = job / "compound-discounts__0" / "result.json"
    r = json.loads(res.read_text())
    r["agent_info"]["model_info"] = {"name": "deepseek-v4-pro", "provider": "anthropic"}
    r["agent_result"].update(n_input_tokens=142322, n_cache_tokens=125056, n_output_tokens=3211, cost_usd=0.9)
    res.write_text(json.dumps(r))
    run, (s,) = runfile.read(import_job(job, tmp_path / "runs"))
    assert run["model"] == {"provider": "deepseek", "name": "deepseek-v4-pro"}
    assert s["cost_source"] == "estimated"
    # 17266 * 1.32 + 125056 * 0.044 + 3211 * 3.96, per million
    assert abs(s["cost_usd"] - 0.041009144) < 1e-9
    assert spent(job) == (s["cost_usd"], 0)
