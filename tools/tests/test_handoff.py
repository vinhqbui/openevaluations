"""The handoff benchmark (P3): freezing predecessor A, the leak check, and the channel tasks."""

import importlib.util
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from oe import REPO, handoff, runfile, schema, site
from oe.import_harbor import import_job
from oe_agents import handoff_settings

SHARED = REPO / "datasets" / "_shared" / "tallyho"
DISCOUNTS = "tallyho/pricing/discounts.py"


def _gen():
    spec = importlib.util.spec_from_file_location("gen_handoff", REPO / "tools" / "gen" / "handoff.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- predecessor A, inside the container -------------------------------------------------------

def test_predecessor_instruction_is_the_goal_plus_the_notes_rule():
    text = handoff_settings.predecessor_instruction("Fix the discounts.\n")
    assert text.startswith("Fix the discounts.")
    assert "NOTES.md" in text and "as you go" in text


def test_freeze_command_tars_the_workspace_without_vcs_or_caches():
    cmd = handoff_settings.freeze_command()
    assert f"{handoff_settings.FREEZE_DIR}/workspace.tar.gz" in cmd
    for x in (".git", ".jj", ".av-task", "__pycache__", ".pytest_cache"):
        assert f"--exclude={x}" in cmd
    assert "-C /app" in cmd


# --- trees, patches, traces ----------------------------------------------------------------------

def _base():
    return handoff.read_tree(SHARED / "src")


def test_read_tree_skips_vcs_caches_and_root_notes(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    for d in (".git", ".jj", "__pycache__", "pkg/__pycache__"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
        (tmp_path / d / "junk").write_text("junk")
    (tmp_path / ".av-task").write_text("{}")
    (tmp_path / "NOTES.md").write_text("notes")
    (tmp_path / "pkg" / "NOTES.md").write_text("a package file, kept")
    assert sorted(handoff.read_tree(tmp_path)) == ["a.py", "pkg/NOTES.md"]


def test_diff_trees_roundtrips_through_git_apply(tmp_path):
    base = _base()
    new = dict(base)
    new[DISCOUNTS] = base[DISCOUNTS].replace(b"percent_total", b"pct_total")
    new["tallyho/pricing/notes_helper.py"] = b"HELPER = 1\n"
    del new["tallyho/report/table.py"]
    patch = handoff.diff_trees(base, new)
    assert "--- /dev/null" in patch and "+++ /dev/null" in patch
    work = tmp_path / "w"
    for rel, data in base.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_bytes(data)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    (tmp_path / "a.patch").write_text(patch, encoding="utf-8", newline="\n")
    subprocess.run(["git", "-c", "core.autocrlf=false", "apply", "--whitespace=nowarn", str(tmp_path / "a.patch")],
                   cwd=work, check=True)  # a Windows git with autocrlf=true would write CRLF
    assert handoff.read_tree(work) == new
    assert handoff.diff_trees(base, base) == ""


def _traj():
    return {"schema_version": "ATIF-v1.8", "agent": {"name": "claude-code", "version": "2.1.316"}, "steps": [
        {"step_id": 1, "source": "user", "message": "Fix the discounts."},
        {"step_id": 2, "source": "agent", "message": "Looking at the code.", "tool_calls": [
            {"tool_call_id": "t1", "function_name": "Read", "arguments": {"file_path": "/app/" + DISCOUNTS}}],
         "observation": {"results": [{"source_call_id": "t1", "content": "x" * 50}]}},
        {"step_id": 3, "source": "agent", "message": [{"type": "text", "text": "Now the notes."}], "tool_calls": [
            {"tool_call_id": "t2", "function_name": "Write",
             "arguments": {"file_path": "/app/NOTES.md", "content": "percent_total is summed"}}]},
    ]}


def test_render_trace_keeps_order_messages_calls_and_truncates_long_output():
    text = handoff.render_trace(_traj(), max_chars=20)
    assert text.index("Fix the discounts.") < text.index("Looking at the code.") < text.index("Now the notes.")
    assert '"file_path": "/app/tallyho/pricing/discounts.py"' in text
    assert "x" * 20 in text and "x" * 21 not in text and "30 more characters" in text
    assert handoff.render_trace(_traj()) == handoff.render_trace(_traj())  # deterministic


# --- the leak check ------------------------------------------------------------------------------

def _markers():
    return handoff.leak_markers(
        hidden_tests={"test_discounts_hidden.py": (SHARED / "tasks/files/test_discounts_hidden.py").read_text()},
        fix_patch=(SHARED / "fixes/discounts.patch").read_text(), base=_base())


def test_leak_markers_skip_lines_already_in_the_base_tree():
    m = _markers()
    assert "test_discounts_hidden" in m["hidden_test"]
    assert any("two_fifty_percent_never_free" in x for x in m["hidden_test"])
    assert "from tallyho.money import Money" not in m["hidden_test"]  # base files have it too
    assert any("remaining = remaining - off[i]" in x for x in m["fix"])
    assert all(len(x) >= handoff.MIN_MARKER for x in m["fix"])


def test_find_leaks_reports_hidden_test_and_fix_lines_per_artifact():
    m = _markers()
    clean = {"NOTES.md": "percentages are summed; should compound", "trace.md": "looked at discounts.py"}
    assert handoff.find_leaks(clean, m) == []
    bad = {"NOTES.md": "see test_two_fifty_percent_never_free", "trace.md": "remaining = remaining - off[i]"}
    found = handoff.find_leaks(bad, m)
    assert [f["artifact"] for f in found if f["kind"] == "hidden_test"] == ["NOTES.md"]
    assert [f["artifact"] for f in found if f["kind"] == "fix"] == ["trace.md"]


# --- oe freeze -------------------------------------------------------------------------------------

def _tar(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel, data in sorted(files.items()):
            info = tarfile.TarInfo("./" + rel)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def fake_a_trial(tmp_path, notes=b"- percentages are summed in apply_discounts\n", edit=True, records=2,
                 task="compound-discounts", name="a", oe_invalid=None):
    base = _base()
    ws = dict(base)
    if edit:
        ws[DISCOUNTS] = base[DISCOUNTS].replace(b"percent_total = Decimal(0)", b"percent_total = Decimal(0)  # wip")
    if notes is not None:
        ws["NOTES.md"] = notes
    t = tmp_path / "jobs" / "handoff-a" / f"{task}__{name}"
    (t / "agent" / "freeze").mkdir(parents=True)
    (t / "agent" / "scholion").mkdir(parents=True)
    (t / "agent" / "freeze" / "workspace.tar.gz").write_bytes(_tar(ws))
    (t / "agent" / "trajectory.json").write_text(json.dumps(_traj()))
    (t / "agent" / "claude-code.txt").write_text('{"type":"result","subtype":"error_max_turns","num_turns":6}\n')
    (t / "agent" / "scholion" / "records.json").write_text(json.dumps({"records": [{"id": i} for i in range(records)]}))
    (t / "result.json").write_text(json.dumps({
        "task_name": f"openevaluations/{task}", "trial_name": t.name,
        "agent_info": {"name": "claude-code", "version": "2.1.316",
                       "model_info": {"name": "deepseek-flash", "provider": "anthropic"}},
        "agent_result": {"metadata": {"av_records": records, **({"oe_invalid": oe_invalid} if oe_invalid else {})}}, "verifier_result": {"rewards": {"reward": 0}},
        "exception_info": None, "started_at": "2026-11-09T05:00:00Z"}))
    return t


def test_freeze_writes_the_frozen_a_and_judges_it_valid(tmp_path):
    out = tmp_path / "frozen"
    a = handoff.freeze(fake_a_trial(tmp_path), out, cut_turns=6)
    assert a["valid"] is True and a["problems"] == []
    assert a["task"] == "compound-discounts" and a["cut_turns"] == 6 and a["a_turns"] == 6
    assert a["agent"] == {"name": "claude-code", "version": "2.1.316"} and a["model"] == "deepseek-flash"
    assert a["files_changed"] == [DISCOUNTS] and a["records"] == 2
    d = out / "compound-discounts"
    assert sorted(p.name for p in d.iterdir()) == ["NOTES.md", "a.json", "records.json", "trajectory.json",
                                                    "workspace.patch"]
    assert "NOTES.md" not in (d / "workspace.patch").read_text()  # notes are their own channel
    assert json.loads((d / "a.json").read_text()) == a
    assert set(a["sha256"]) == {"NOTES.md", "records.json", "trajectory.json", "workspace.patch"}


def test_freeze_leaves_out_binary_files_and_says_so(tmp_path):
    t = fake_a_trial(tmp_path)
    tar = t / "agent" / "freeze" / "workspace.tar.gz"
    with tarfile.open(tar, "r:gz") as tf:
        files = {m.name.removeprefix("./"): tf.extractfile(m).read() for m in tf.getmembers() if m.isfile()}
    files[".coverage"] = b"\xff\xfe\x00binary"
    tar.write_bytes(_tar(files))
    a = handoff.freeze(t, tmp_path / "frozen", cut_turns=6)
    assert a["valid"] is True and a["binary_files_left_out"] == [".coverage"]
    assert ".coverage" not in (tmp_path / "frozen" / "compound-discounts" / "workspace.patch").read_text()


@pytest.mark.parametrize("kw, problem", [
    ({"notes": None}, "no NOTES.md"),
    ({"notes": b"  \n"}, "no NOTES.md"),
    ({"edit": False}, "changed no file"),
    ({"records": 0}, "no Scholion records"),
    ({"oe_invalid": "the av hooks never fired"}, "av session invalid: the av hooks never fired"),
])
def test_freeze_marks_a_predecessor_that_left_a_channel_empty_invalid(tmp_path, kw, problem):
    a = handoff.freeze(fake_a_trial(tmp_path, **kw), tmp_path / "frozen", cut_turns=6)
    assert a["valid"] is False and any(problem in p for p in a["problems"])


def test_freeze_cli_takes_a_job_and_writes_one_a_per_task(tmp_path):
    from oe.cli import main

    fake_a_trial(tmp_path, task="compound-discounts")
    fake_a_trial(tmp_path, task="csv-escaping", name="b")
    assert main(["freeze", str(tmp_path / "jobs" / "handoff-a"), "--out", str(tmp_path / "frozen"),
                 "--cut-turns", "6"]) == 0
    assert sorted(p.name for p in (tmp_path / "frozen").iterdir()) == ["compound-discounts", "csv-escaping"]


# --- the generated channel tasks -------------------------------------------------------------------

def _frozen(tmp_path, **kw):
    out = tmp_path / "shared" / "interrupt"
    handoff.freeze(fake_a_trial(tmp_path, **kw), out, cut_turns=6)
    return out


def test_generator_writes_one_task_per_channel_differing_only_in_the_channel(tmp_path):
    gen = _gen()
    names = gen.generate(_frozen(tmp_path), tmp_path / "ds", family="interrupt")
    assert names == [f"compound-discounts--{c}" for c in handoff.BUILT_CHANNELS]
    ds = tmp_path / "ds"
    ins = {c: (ds / f"compound-discounts--{c}" / "instruction.md").read_text() for c in handoff.BUILT_CHANNELS}
    goal = (SHARED / "tasks" / "compound-discounts.toml").read_text().split('"""')[1].strip()
    for c, text in ins.items():
        assert text.rstrip().endswith(goal)
        assert "was stopped before it finished" in text and "git diff" in text
    assert "/handoff/trace.md" in ins["trace"] and "NOTES.md" in ins["notes"]
    assert "trace" not in ins["repo-only"] and "NOTES" not in ins["repo-only"]
    for c in handoff.BUILT_CHANNELS:
        t = ds / f"compound-discounts--{c}"
        assert (t / "tests" / "test_discounts_hidden.py").read_bytes() == \
            (SHARED / "tasks/files/test_discounts_hidden.py").read_bytes()
        assert (t / "solution" / "fix.patch").exists() and os.access(t / "solution" / "solve.sh", os.X_OK)
        assert os.access(t / "tests" / "test.sh", os.X_OK)
        env = sorted(p.relative_to(t / "environment").as_posix() for p in (t / "environment").rglob("*")
                     if p.is_file() and "src/" not in p.as_posix())
        want = {"repo-only": [], "trace": ["handoff/trace.md"], "notes": ["handoff/NOTES.md"]}[c]
        assert env == sorted(["Dockerfile", "a.patch", *want])
        dockerfile = (t / "environment" / "Dockerfile").read_text()
        assert "git apply" in dockerfile and "rm /tmp/a.patch" in dockerfile
        assert ("mv /handoff/NOTES.md /app/NOTES.md" in dockerfile) == (c == "notes")
        assert "fix.patch" not in dockerfile and "hidden" not in dockerfile
        toml = (t / "task.toml").read_text()
        assert f'name = "openevaluations/compound-discounts--{c}"' in toml
        assert f'channel = "{c}"' in toml and 'family = "interrupt"' in toml


def test_generator_refuses_an_invalid_or_leaky_predecessor(tmp_path):
    gen = _gen()
    with pytest.raises(SystemExit, match="invalid"):
        gen.generate(_frozen(tmp_path, notes=None), tmp_path / "ds", family="interrupt")
    leaky = tmp_path / "leaky"
    with pytest.raises(SystemExit, match="leak"):
        gen.generate(_frozen(leaky, notes=b"test_two_fifty_percent_never_free\n"), leaky / "ds", family="interrupt")


def test_fix_lines_refuse_a_curated_relay_a_but_only_count_for_a_real_interrupted_a(tmp_path):
    """A real A never saw the fix (the image cannot hold it), so fix lines in its artifacts are its
    own progress; in a curated A they would be our leak."""
    gen = _gen()
    src = _frozen(tmp_path, notes=b"- try: remaining = remaining - off[i]\n")
    gen.generate(src, tmp_path / "ds", family="interrupt")
    meta = (tmp_path / "ds" / "compound-discounts--notes" / "task.toml").read_text()
    assert "fix_lines_in_a = 1" in meta
    with pytest.raises(SystemExit, match="leak"):
        gen.generate(src, tmp_path / "ds2", family="relay")


def test_generator_oracle_reverts_a_then_applies_the_fix(tmp_path):
    gen = _gen()
    gen.generate(_frozen(tmp_path), tmp_path / "ds", family="interrupt")
    solve = (tmp_path / "ds" / "compound-discounts--notes" / "solution" / "solve.sh").read_text()
    assert solve.index("reset -q --hard") < solve.index("clean -fdq") < solve.index("git apply")
    assert "safe.directory" in solve


def test_frozen_patch_applies_to_the_image_tree_and_the_fix_applies_after_the_oracle_reset(tmp_path):
    """What the Dockerfile and solve.sh do, with git on the host: A's patch on the base tree."""
    d = _frozen(tmp_path) / "compound-discounts"
    work = tmp_path / "app"
    for rel, data in _base().items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_bytes(data)
    g = ["git", "-c", "user.name=oe", "-c", "user.email=oe@localhost"]
    subprocess.run(g + ["init", "-q"], cwd=work, check=True)
    subprocess.run(g + ["add", "-A"], cwd=work, check=True)
    subprocess.run(g + ["commit", "-qm", "base"], cwd=work, check=True)
    subprocess.run(["git", "apply", str(d / "workspace.patch")], cwd=work, check=True)
    assert b"# wip" in (work / DISCOUNTS).read_bytes()
    subprocess.run(["git", "reset", "-q", "--hard"], cwd=work, check=True)
    subprocess.run(["git", "apply", str(SHARED / "fixes" / "discounts.patch")], cwd=work, check=True)


def test_generator_check_mode_reports_staleness(tmp_path):
    gen = _gen()
    src, ds = _frozen(tmp_path), tmp_path / "ds"
    gen.generate(src, ds, family="interrupt")
    assert gen.stale(src, ds, family="interrupt") == []
    (ds / "compound-discounts--trace" / "instruction.md").write_text("edited")
    assert gen.stale(src, ds, family="interrupt") != []


# --- importing successor runs, and the site ---------------------------------------------------------

def fake_b_job(tmp_path, channels=("repo-only", "notes", "trace"), k=2):
    job = tmp_path / "jobs" / "handoff-b"
    for c in channels:
        for i in range(k):
            t = job / f"compound-discounts--{c}__{i}"
            (t / "agent").mkdir(parents=True)
            (t / "result.json").write_text(json.dumps({
                "task_name": f"openevaluations/compound-discounts--{c}", "trial_name": t.name,
                "agent_info": {"name": "claude-code", "version": "2.1.316",
                               "model_info": {"name": "deepseek-flash", "provider": "anthropic"}},
                "agent_result": {"n_input_tokens": 1000 if c == "repo-only" else 800, "n_cache_tokens": 0,
                                 "n_output_tokens": 100, "cost_usd": None, "metadata": {}},
                "verifier_result": {"rewards": {"reward": 1}}, "exception_info": None,
                "started_at": f"2026-11-09T06:0{i}:00Z",
                "agent_execution": {"started_at": "2026-11-09T06:00:00Z", "finished_at": "2026-11-09T06:00:30Z"}}))
            (t / "agent" / "claude-code.txt").write_text('{"type":"result","num_turns":5}\n')
    (job / "oe-env.json").write_text(json.dumps({"dataset": "handoff-interrupt", "attempts": k,
                                                 "prereg": "docs/PREREG-handoff-interrupt.md"}))
    return job


def test_import_harbor_splits_channel_tasks_into_task_and_arm(tmp_path):
    p = import_job(fake_b_job(tmp_path), tmp_path / "runs", channels=True)
    assert schema.validate_file(p) == []
    run, ss = runfile.read(p)
    assert run["config"]["arm"] == "multi" and run["config"]["arms"] == ["notes", "repo-only", "trace"]
    assert {s["task"] for s in ss} == {"compound-discounts"}
    assert sorted({s["arm"] for s in ss}) == ["notes", "repo-only", "trace"]
    assert sorted((s["arm"], s["attempt"]) for s in ss)[:2] == [("notes", 1), ("notes", 2)]


def test_site_shows_a_harbor_handoff_run_paired_against_repo_only(tmp_path):
    runs = tmp_path / "runs"
    import_job(fake_b_job(tmp_path), runs, channels=True)
    site.build(runs, tmp_path / "data")
    (r,) = json.loads((tmp_path / "data" / "handoff.json").read_text())["runs"]
    assert r["family"] == "interrupt"
    cells = {c["arm"]: c for c in r["cells"]}
    assert set(cells) == {"repo-only", "notes", "trace"}
    assert "vs_repo_only" not in cells["repo-only"]
    assert cells["notes"]["vs_repo_only"]["tokens"][0] == pytest.approx(900 / 1100 - 1)
    assert cells["trace"]["channel"] == "trace"


# --- the Harbor agent for A (only where Harbor is installed: `uv sync --extra run`) ---------------

def test_handoff_a_needs_a_cut_and_freezes_after_the_av_run(tmp_path, monkeypatch):
    pytest.importorskip("harbor")
    import asyncio

    from oe_agents.claude_code_av import ClaudeCodeAv
    from oe_agents.handoff_a import HandoffA

    with pytest.raises(ValueError, match="max_turns"):
        HandoffA(logs_dir=tmp_path, model_name="anthropic/deepseek-flash")
    a = HandoffA(logs_dir=tmp_path, model_name="anthropic/deepseek-flash", max_turns=6)
    assert HandoffA.name() == "claude-code" and isinstance(a, ClaudeCodeAv)
    calls = []

    async def fake_run(self, instruction, environment, context):
        calls.append(("run", instruction))
        raise RuntimeError("cut")  # the freeze must still happen

    async def fake_quiet(self, environment, command, timeout_sec=60):
        calls.append(("quiet", command))

    monkeypatch.setattr(ClaudeCodeAv, "run", fake_run)
    monkeypatch.setattr(ClaudeCodeAv, "_quiet", fake_quiet)
    with pytest.raises(RuntimeError, match="cut"):
        asyncio.run(a.run("Fix the discounts.", None, None))
    assert calls[0] == ("run", handoff_settings.predecessor_instruction("Fix the discounts."))
    assert calls[1] == ("quiet", handoff_settings.freeze_command())


def test_rewards_check_passes_only_when_every_trial_scored_the_expected_reward(tmp_path, capsys):
    from oe.cli import main

    job = fake_b_job(tmp_path, channels=("repo-only",), k=2)  # every reward 1
    assert main(["rewards", str(job), "--expect", "1"]) == 0
    assert main(["rewards", str(job), "--expect", "0"]) == 1
    assert "compound-discounts--repo-only" in capsys.readouterr().out
    r = json.loads((job / "compound-discounts--repo-only__0" / "result.json").read_text())
    r["exception_info"] = {"exception_type": "AgentTimeoutError"}
    (job / "compound-discounts--repo-only__0" / "result.json").write_text(json.dumps(r))
    assert main(["rewards", str(job), "--expect", "1"]) == 1


def test_channel_jobs_of_one_successor_merge_into_one_run(tmp_path):
    from oe.cli import main

    jobs = []
    for c in ("repo-only", "trace"):
        j = fake_b_job(tmp_path / c, channels=(c,))
        jobs.append(j.rename(tmp_path / f"handoff-b-claude-code-{c}"))
    out = tmp_path / "runs"
    assert main(["import-harbor", *map(str, jobs), "--channels", "--merge", "--out", str(out)]) == 0
    (p,) = out.glob("*.jsonl")
    run, ss = runfile.read(p)
    assert run["config"]["arms"] == ["repo-only", "trace"] and len(ss) == 4
    assert {s["trajectory"]["kind"] for s in ss} == {"none"}
    assert schema.validate_file(p) == []


# --- the cross-vendor family (docs/PREREG-handoff-xvendor.md) ------------------------------------

def test_wrapup_message_names_no_channel():
    msg = handoff_settings.WRAPUP_MESSAGE
    assert "Do not change any code" in msg and "another engineer" in msg
    for word in ("NOTES", "notes", "av ", "Scholion", "record"):
        assert word not in msg


def test_freeze_command_can_name_the_cut_tree():
    cmd = handoff_settings.freeze_command("workspace-cut")
    assert f"{handoff_settings.FREEZE_DIR}/workspace-cut.tar.gz" in cmd
    assert "workspace.tar.gz" not in cmd


def test_freeze_of_a_wrapped_up_a_takes_turns_from_the_cut_and_reports_the_wrapup(tmp_path):
    t = fake_a_trial(tmp_path)
    (t / "agent" / "claude-code-cut.txt").write_text('{"type":"result","subtype":"error_max_turns","num_turns":4}\n')
    (t / "agent" / "claude-code.txt").write_text('{"type":"result","subtype":"success","num_turns":2}\n')
    base = _base()
    cut = dict(base)
    cut[DISCOUNTS] = base[DISCOUNTS].replace(b"percent_total = Decimal(0)", b"percent_total = Decimal(0)  # wip")
    cut["NOTES.md"] = b"older notes\n"
    (t / "agent" / "freeze" / "workspace-cut.tar.gz").write_bytes(_tar(cut))
    a = handoff.freeze(t, tmp_path / "frozen", cut_turns=4)
    assert a["valid"] is True and a["a_turns"] == 4 and a["a_stop"] == "error_max_turns"
    assert a["wrapup_turns"] == 2 and a["wrapup_stop"] == "success"
    assert a["wrapup_changed_files"] == []  # only NOTES.md changed in the wrap-up
    cut[DISCOUNTS] = base[DISCOUNTS]
    (t / "agent" / "freeze" / "workspace-cut.tar.gz").write_bytes(_tar(cut))
    a = handoff.freeze(t, tmp_path / "frozen2", cut_turns=4)
    assert a["wrapup_changed_files"] == [DISCOUNTS]


def test_an_unwrapped_freeze_has_no_wrapup_fields(tmp_path):
    a = handoff.freeze(fake_a_trial(tmp_path), tmp_path / "frozen", cut_turns=6)
    assert not any(k.startswith("wrapup") for k in a)


def test_xvendor_families_build_repo_only_records_and_notes(tmp_path):
    gen = _gen()
    src = tmp_path / "shared" / "xv-sonnet"
    handoff.freeze(fake_a_trial(tmp_path), src, cut_turns=4)
    names = gen.generate(src, tmp_path / "ds", family="xv-sonnet")
    assert names == [f"compound-discounts--{c}" for c in ("repo-only", "records", "notes")]
    t = tmp_path / "ds" / "compound-discounts--records"
    env = sorted(p.relative_to(t / "environment").as_posix() for p in (t / "environment").rglob("*")
                 if p.is_file() and "src/" not in p.as_posix())
    assert env == ["Dockerfile", "a.patch", "handoff/a.patch", "handoff/records.json"]
    frozen = src / "compound-discounts"
    assert (t / "environment" / "handoff" / "a.patch").read_bytes() == (frozen / "workspace.patch").read_bytes()
    assert (t / "environment" / "handoff" / "records.json").read_bytes() == (frozen / "records.json").read_bytes()
    dockerfile = (t / "environment" / "Dockerfile").read_text()
    assert "COPY handoff/ /handoff/" in dockerfile and "chown -R agent:agent /app /handoff" in dockerfile
    ins = (t / "instruction.md").read_text()
    assert "git diff" in ins and "av" in ins and "context pack" in ins
    assert "NOTES" not in ins
    assert 'family = "xv-sonnet"' in (t / "task.toml").read_text()
    assert "PREREG-handoff-xvendor.md" in (tmp_path / "ds" / "README.md").read_text()
    for c in ("repo-only", "notes"):
        df = (tmp_path / "ds" / f"compound-discounts--{c}" / "environment" / "Dockerfile").read_text()
        assert "records" not in df


def test_handoff_a_wraps_up_after_the_cut_with_continue_and_its_own_turns(tmp_path, monkeypatch):
    pytest.importorskip("harbor")
    import asyncio

    from harbor.agents.installed.claude_code import ClaudeCode

    from oe_agents.handoff_a import HandoffA

    a = HandoffA(logs_dir=tmp_path, model_name="anthropic/claude-sonnet-5-5", max_turns=4, wrapup_turns=3)
    calls = []

    async def fake_claude(self, instruction, environment, context):
        calls.append(("claude", instruction, self.options.max_turns, self._resume))

    async def fake_quiet(self, environment, command, timeout_sec=60):
        calls.append(("quiet", command))

    async def fake_exec(self, environment, command, **kw):
        calls.append(("exec", command))

    monkeypatch.setattr(ClaudeCode, "run", fake_claude)
    monkeypatch.setattr(HandoffA, "_quiet", fake_quiet)
    monkeypatch.setattr(HandoffA, "exec_as_agent", fake_exec)
    asyncio.run(a._run_claude("goal", None, None))
    assert calls[0] == ("claude", "goal", 4, False)
    assert calls[1] == ("quiet", handoff_settings.freeze_command("workspace-cut"))
    assert calls[2][0] == "exec" and "claude-code-cut.txt" in calls[2][1]
    assert calls[3] == ("claude", handoff_settings.WRAPUP_MESSAGE, 3, True)
    assert a.options.max_turns == 4 and a._resume is False
    calls.clear()
    plain = HandoffA(logs_dir=tmp_path, model_name="anthropic/deepseek-flash", max_turns=6)
    asyncio.run(plain._run_claude("goal", None, None))
    assert calls == [("claude", "goal", 6, False)]


def test_handoff_a_treats_the_turn_cap_as_the_cut_but_reraises_other_failures(tmp_path, monkeypatch):
    pytest.importorskip("harbor")
    import asyncio
    from types import SimpleNamespace

    from harbor.agents.installed.claude_code import ClaudeCode

    from oe_agents.handoff_a import HandoffA

    a = HandoffA(logs_dir=tmp_path, model_name="anthropic/deepseek-flash", max_turns=4)

    async def failing(self, instruction, environment, context):
        raise RuntimeError("claude exited 1")

    class Env:
        def __init__(self, rc):
            self.rc, self.cmds = rc, []

        async def exec(self, command, **kw):
            self.cmds.append(command)
            return SimpleNamespace(return_code=self.rc, stdout="", stderr="")

    monkeypatch.setattr(ClaudeCode, "run", failing)
    env = Env(0)
    asyncio.run(a._run_claude("goal", env, None))  # the turn cap: no raise
    assert "error_max_turns" in env.cmds[0]
    with pytest.raises(RuntimeError, match="exited"):
        asyncio.run(a._run_claude("goal", Env(1), None))


def test_handoff_a_adds_the_cut_cost_to_the_wrapup_cost(tmp_path, monkeypatch):
    pytest.importorskip("harbor")
    from harbor.models.agent.context import AgentContext

    from oe_agents.claude_code_av import ClaudeCodeAv
    from oe_agents.handoff_a import HandoffA

    a = HandoffA(logs_dir=tmp_path, model_name="anthropic/claude-sonnet-5-5", max_turns=4, wrapup_turns=3)
    (tmp_path / "claude-code-cut.txt").write_text('{"type":"result","num_turns":4,"total_cost_usd":0.10}\n')
    (tmp_path / "claude-code.txt").write_text('{"type":"result","num_turns":2,"total_cost_usd":0.03}\n')
    ctx = AgentContext()
    ctx.cost_usd = 0.03
    monkeypatch.setattr(ClaudeCodeAv, "populate_context_post_run", lambda self, context: None)
    a.populate_context_post_run(ctx)
    assert ctx.cost_usd == pytest.approx(0.13)
    assert ctx.metadata["a_cut_turns"] == 4 and ctx.metadata["a_wrapup_turns"] == 2


def test_handoff_b_adopts_a_before_the_swap_and_deletes_the_handoff_dir(tmp_path, monkeypatch):
    pytest.importorskip("harbor")
    import asyncio
    from types import SimpleNamespace

    from oe_agents.claude_code_av import ClaudeCodeAv
    from oe_agents.handoff_b import HandoffBAv, adopt_command

    b = HandoffBAv(logs_dir=tmp_path, model_name="anthropic/claude-sonnet-5-5", max_turns=40)
    assert isinstance(b, ClaudeCodeAv) and HandoffBAv.name() == "claude-code"
    assert HandoffBAv.START_ARGS == " --base-rev HEAD" and ClaudeCodeAv.START_ARGS == ""
    calls = []

    class Env:
        def __init__(self, rc):
            self.rc = rc

        async def exec(self, command, **kw):
            calls.append(("probe", command))
            return SimpleNamespace(return_code=self.rc, stdout="", stderr="")

    async def as_agent(self, environment, command, **kw):
        calls.append(("agent", command))

    async def as_root(self, environment, command, **kw):
        calls.append(("root", command))

    monkeypatch.setattr(HandoffBAv, "exec_as_agent", as_agent)
    monkeypatch.setattr(HandoffBAv, "exec_as_root", as_root)
    asyncio.run(b._prepare_workspace(Env(0), "/home/agent/ws/app/t"))
    assert [c[0] for c in calls] == ["probe", "agent", "root"]
    assert calls[1][1] == adopt_command("/home/agent/ws/app/t") and "adopt --ws /home/agent/ws/app/t" in calls[1][1]
    assert calls[2][1] == "rm -rf /handoff"
    with pytest.raises(RuntimeError, match="records channel"):
        asyncio.run(b._prepare_workspace(Env(1), "/ws"))
