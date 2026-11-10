"""The cross-vendor handoff driver (oe.xvendor): key isolation, round order, budget gate, report."""

import json

import pytest

from oe import runfile, xvendor
from oe.import_harbor import import_job

ENV = {"PATH": "/bin", "ANTHROPIC_API_KEY": "stale", "ANTHROPIC_BASE_URL": "http://old",
       "ANTHROPIC_AUTH_TOKEN": "stale-token", "CLAUDE_API_KEY": "ck", "DEEPSEEK_API_KEY": "dk",
       "CLAUDE_CODE_OAUTH_TOKEN": "oauth", "CLAUDE_CODE_SESSION_ID": "s", "CLAUDECODE": "1",
       "AWS_BEARER_TOKEN_BEDROCK": "aws", "ANTHROPIC_MODEL": "m"}


def test_each_leg_gets_only_its_own_endpoint_and_key():
    c = xvendor.leg_env("claude", ENV)
    assert c["ANTHROPIC_API_KEY"] == "ck"
    assert "dk" not in c.values() and "stale" not in c.values() and "stale-token" not in c.values()
    assert not {"ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_API_KEY", "DEEPSEEK_API_KEY"} & set(c)
    for e in (c, xvendor.leg_env("deepseek", ENV)):
        assert not {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_SESSION_ID", "CLAUDECODE", "AWS_BEARER_TOKEN_BEDROCK",
                    "ANTHROPIC_MODEL"} & set(e)
    d = xvendor.leg_env("deepseek", ENV)
    assert d["ANTHROPIC_AUTH_TOKEN"] == "dk" and d["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert "ck" not in d.values() and not {"ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "DEEPSEEK_API_KEY"} & set(d)
    for e in (c, d):
        assert e["PATH"] == "/bin" and e["DOCKER_BUILDKIT"] == "0" and e["PYTHONUTF8"] == "1"


def test_directions_cross_vendors_and_successors_are_claude_code():
    for d in xvendor.DIRECTIONS.values():
        assert d["a"] != d["b"]
    assert xvendor.DIRECTIONS["sonnet-to-flash"] == {"family": "xv-sonnet", "a": "claude", "b": "deepseek"}
    assert set(xvendor.AGENTS) == {"repo-only", "records", "notes"}


def test_plan_runs_every_cell_once_per_round():
    p = xvendor.plan(["repo-only", "records"], 2, tasks=("t1", "t2"))
    assert p[:4] == [(1, "t1", "repo-only"), (1, "t1", "records"), (1, "t2", "repo-only"), (1, "t2", "records")]
    assert len(p) == 8 and p[4][0] == 2


def _trial(job, started=True, exc=None, cost=0.1, name="t__x"):
    t = job / name
    t.mkdir(parents=True)
    (t / "result.json").write_text(json.dumps({
        "trial_name": name, "task_name": "openevaluations/compound-discounts--repo-only",
        "agent_info": {"name": "claude-code", "model_info": {"name": "claude-sonnet-5-5"}},
        "agent_result": {"cost_usd": cost, "n_input_tokens": 10, "n_cache_tokens": 0, "n_output_tokens": 1},
        "exception_info": exc, "agent_execution": {"started_at": "2026-11-10T00:00:00Z"} if started else None}))


def test_cell_state_resumes_and_reruns_a_setup_failure_once(tmp_path):
    fam, arm, task = "xv-flash", "repo-only", "compound-discounts"
    job = tmp_path / xvendor.job_name(fam, arm, task, 1)
    assert xvendor.cell_state(tmp_path, fam, arm, task, 1) == ("todo", job)
    _trial(job, started=False, exc={"exception_type": "AgentSetupTimeoutError"})
    assert xvendor.cell_state(tmp_path, fam, arm, task, 1) == ("retry", job.with_name(job.name + "-retry"))
    _trial(job.with_name(job.name + "-retry"), started=False, exc={"exception_type": "AgentSetupTimeoutError"})
    assert xvendor.cell_state(tmp_path, fam, arm, task, 1)[0] == "done"  # re-run once only
    job2 = tmp_path / xvendor.job_name(fam, arm, task, 2)
    _trial(job2, exc={"exception_type": "NonZeroAgentExitCodeError"})  # the agent ran: a result
    assert xvendor.cell_state(tmp_path, fam, arm, task, 2) == ("done", job2)
    job3 = tmp_path / xvendor.job_name(fam, arm, task, 3)
    job3.mkdir()  # killed: no result, never re-run
    assert xvendor.cell_state(tmp_path, fam, arm, task, 3) == ("done", job3)


def test_budget_gate_reserves_a_ceiling_per_unfinished_job_and_one_more(tmp_path, monkeypatch):
    monkeypatch.setitem(xvendor.VENDORS, "claude", {**xvendor.VENDORS["claude"], "cap": 1.0, "ceiling": 0.3})
    _trial(tmp_path / "j1", cost=0.3)
    assert xvendor.may_launch("claude", root=tmp_path)[0] is True  # 0.3 + 0.3 <= 1.0
    (tmp_path / "j2").mkdir()  # in flight or killed
    assert xvendor.may_launch("claude", root=tmp_path)[0] is True  # 0.3 + 0.6
    (tmp_path / "j3").mkdir()
    ok, why = xvendor.may_launch("claude", root=tmp_path)
    assert ok is False and "cap" in why  # 0.3 + 0.9 > 1.0
    assert xvendor.vendor_spend("claude", tmp_path) == (pytest.approx(0.3), 0, 2)


def test_a_setup_failure_costs_nothing_and_does_not_stop_the_gate(tmp_path):
    t = tmp_path / "j1" / "t__x"
    t.mkdir(parents=True)
    (t / "result.json").write_text(json.dumps({"trial_name": "t__x", "agent_info": {"name": "claude-code",
                                               "model_info": {"name": "claude-sonnet-5-5"}}, "agent_result": None,
                                               "exception_info": {"exception_type": "AgentSetupTimeoutError"},
                                               "agent_execution": None}))
    assert xvendor.vendor_spend("claude", tmp_path) == (0.0, 0, 0)
    assert xvendor.may_launch("claude", root=tmp_path)[0] is True


def test_budget_gate_stops_on_an_unpriced_trial(tmp_path):
    t = tmp_path / "j1" / "t__x"
    t.mkdir(parents=True)
    (t / "result.json").write_text(json.dumps({"trial_name": "t__x", "agent_info": {"name": "claude-code",
                                               "model_info": {"name": "mystery"}}, "agent_result": {}}))
    ok, why = xvendor.may_launch("claude", root=tmp_path)
    assert ok is False and "price" in why


def test_b_command_uses_the_successor_vendor_and_the_records_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(xvendor, "pinned_version", lambda: "2.1.400")
    cmd = xvendor.b_command("flash-to-sonnet", "records", "csv-escaping", "job")
    s = " ".join(cmd)
    assert "-a oe_agents.handoff_b:HandoffBAv" in s and "-m anthropic/claude-sonnet-5-5" in s
    assert "max_budget_usd=0.75" in s and "av_version=release/0.0.2" in s and "version=2.1.400" in s
    assert s.replace("\\", "/").count("handoff-xv-flash/csv-escaping--records") == 1
    cmd = xvendor.b_command("sonnet-to-flash", "repo-only", "csv-escaping", "job")
    s = " ".join(cmd)
    assert "-a claude-code" in s and "-m anthropic/deepseek-flash" in s and "max_budget" not in s
    assert "CLAUDE_CODE_SUBAGENT_MODEL=deepseek-flash" in s and "-k 1" in s and "-r 0" in s


def test_steps_before_stop_feedback():
    traj = {"steps": [{"source": "user", "message": "goal"}, {"source": "agent"}, {"source": "agent"},
                      {"source": "user", "message": "Stop hook feedback: av: no record explains your changes"},
                      {"source": "agent"}]}
    assert xvendor.steps_before_stop_feedback(traj) == 2
    assert xvendor.steps_before_stop_feedback({"steps": [{"source": "agent"}] * 3}) == 3


def test_report_counts_sessions_whose_agent_ran(tmp_path):
    from test_handoff import fake_b_job

    job = fake_b_job(tmp_path, channels=("repo-only", "records"), k=3)
    r = json.loads((job / "compound-discounts--records__0" / "result.json").read_text())
    r["verifier_result"] = {"rewards": {"reward": 0}}
    r["exception_info"] = {"exception_type": "NonZeroAgentExitCodeError"}  # hit the turn cap: unsolved, counted
    (job / "compound-discounts--records__0" / "result.json").write_text(json.dumps(r))
    r = json.loads((job / "compound-discounts--records__1" / "result.json").read_text())
    r["agent_result"]["metadata"] = {"oe_invalid": "the av hooks never fired"}
    (job / "compound-discounts--records__1" / "result.json").write_text(json.dumps(r))
    r = json.loads((job / "compound-discounts--repo-only__2" / "result.json").read_text())
    r["exception_info"] = {"exception_type": "NonZeroAgentExitCodeError"}  # e.g. adopt failed: Claude never ran
    (job / "compound-discounts--repo-only__2" / "result.json").write_text(json.dumps(r))
    (job / "compound-discounts--repo-only__2" / "agent" / "claude-code.txt").unlink()
    p = import_job(job, tmp_path / "runs", channels=True)
    rows = {row["arm"]: row for row in xvendor.report(p)}
    assert rows["repo-only"]["n"] == 2 and rows["repo-only"]["solved"] == 2 and rows["repo-only"]["rate"] == 1.0
    assert rows["repo-only"]["no_result"] == 1
    assert rows["records"]["n"] == 2 and rows["records"]["solved"] == 1 and rows["records"]["invalid"] == 1
    assert rows["records"]["median_turns"] == 5
    assert rows["records"]["cost_per_solved"] == pytest.approx(rows["records"]["cost_total"])
    run, _ = runfile.read(p)
    assert run["config"]["arms"] == ["records", "repo-only"]


def test_site_pairs_an_xvendor_run_against_repo_only(tmp_path):
    from test_handoff import fake_b_job

    from oe import site

    job = fake_b_job(tmp_path, channels=("repo-only", "records"), k=2)
    env = json.loads((job / "oe-env.json").read_text())
    (job / "oe-env.json").write_text(json.dumps({**env, "dataset": "handoff-xv-flash"}))
    import_job(job, tmp_path / "runs", channels=True)
    site.build(tmp_path / "runs", tmp_path / "data")
    (r,) = json.loads((tmp_path / "data" / "handoff.json").read_text())["runs"]
    assert r["family"] == "xv-flash"
    cells = {c["arm"]: c for c in r["cells"]}
    assert "vs_repo_only" in cells["records"] and "vs_repo_only" not in cells["repo-only"]
