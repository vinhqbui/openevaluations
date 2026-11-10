"""The Scholion arm: Claude Code with av hooks, a daemon and a jj workspace, as a Harbor agent."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from oe_agents import av_container, av_settings
from oe_agents.av_settings import LOG, evaluate, hook_settings, merge_settings


def test_hook_settings_mirror_scholion_bench_with_jit_hooks():
    s = hook_settings(budget=800, jit=True)
    hooks = s["hooks"]
    assert set(hooks) == {"SessionStart", "PostToolUse", "PreToolUse", "Stop"}
    assert hooks["PostToolUse"][0]["matcher"] == "Edit|Write|MultiEdit|NotebookEdit"
    assert hooks["PreToolUse"][0]["matcher"] == "Read|Edit|MultiEdit"
    names = {"SessionStart": "session-start", "PostToolUse": "post-edit", "PreToolUse": "pre-read", "Stop": "stop"}
    for event, name in names.items():
        (cmd,) = [h["command"] for h in hooks[event][0]["hooks"]]
        assert cmd.startswith(f"echo {name} >> {LOG}/hook-count; ")
        assert "AV_HOOK_WAIT_SECS=0" in cmd and "AV_AGENT=claude-code" in cmd
        assert f" hook {name}" in cmd
        assert cmd.endswith("exit 0")  # a hook must never fail the agent's turn
    assert "--budget 800" in hooks["SessionStart"][0]["hooks"][0]["command"]
    assert "session-start.md" in hooks["SessionStart"][0]["hooks"][0]["command"]


def test_without_jit_only_session_start_and_post_edit():
    assert set(hook_settings(jit=False)["hooks"]) == {"SessionStart", "PostToolUse"}


def test_merge_settings_keeps_user_hooks_and_appends_ours():
    user = {"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "true"}]}]}}
    merged = merge_settings(user, hook_settings())
    assert merged["model"] == "x"
    assert merged["hooks"]["Stop"][0]["hooks"][0]["command"] == "true"
    assert len(merged["hooks"]["Stop"]) == 2
    assert user["hooks"]["Stop"] == [{"hooks": [{"type": "command", "command": "true"}]}]  # not mutated


def _logdir(tmp_path, count="session-start\npost-edit\nstop\n", pack="# Task\nstuff", err="", finish=None):
    d = tmp_path / "scholion"
    d.mkdir()
    if count is not None:
        (d / "hook-count").write_text(count)
    if pack is not None:
        (d / "session-start.md").write_text(pack)
    (d / "hooks.err").write_text(err)
    fin = {"checkpoint_ok": True, "healthz": "ok", "record_count": 2} if finish is None else finish
    (d / "finish.json").write_text(json.dumps(fin))
    (d / "av-version.txt").write_text("scholion 0.0.2\n")
    return d


def test_evaluate_valid_session_reports_counts(tmp_path):
    m = evaluate(_logdir(tmp_path))
    assert "oe_invalid" not in m
    assert m["av_hook_counts"] == {"session-start": 1, "post-edit": 1, "stop": 1}
    assert m["av_pack_chars"] == len("# Task\nstuff") and m["av_records"] == 2
    assert m["av_checkpoint_ok"] is True and m["av_version"] == "scholion 0.0.2"


@pytest.mark.parametrize("kw, reason", [
    ({"count": None}, "the av hooks never fired"),
    ({"count": ""}, "the av hooks never fired"),
    ({"count": "post-edit\n"}, "the av hooks never fired"),  # no session-start: no pack was delivered
    ({"pack": "  \n"}, "empty session-start pack"),
    ({"err": "error: claim lost (422)\n"}, "av hook errors: error: claim lost (422)"),
    ({"finish": {"checkpoint_ok": False, "healthz": "ok"}}, "final checkpoint failed"),
    ({"finish": {}}, "final checkpoint failed"),
])
def test_evaluate_marks_invalid_sessions(tmp_path, kw, reason):
    assert evaluate(_logdir(tmp_path, **kw))["oe_invalid"] == reason


def test_evaluate_without_log_dir_is_invalid(tmp_path):
    assert evaluate(tmp_path / "missing")["oe_invalid"] == "the av hooks never fired"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   check=True, capture_output=True)


def test_tree_matches_compares_every_tracked_file(tmp_path):
    base = tmp_path / "base"
    (base / "pkg").mkdir(parents=True)
    (base / "pkg" / "a.py").write_bytes(b"x = 1\n")
    (base / "b.txt").write_bytes(b"b\n")
    _git(base, "init", "-q")
    _git(base, "add", "-A")
    _git(base, "commit", "-qm", "base")
    ws = tmp_path / "ws"
    (ws / "pkg").mkdir(parents=True)
    (ws / "pkg" / "a.py").write_bytes(b"x = 1\n")
    (ws / "b.txt").write_bytes(b"b\n")
    (ws / ".jj").mkdir()
    assert av_container.tree_matches(base, ws) == []
    (ws / "pkg" / "a.py").write_bytes(b"x = 2\n")
    (ws / "b.txt").unlink()
    assert av_container.tree_matches(base, ws) == ["b.txt", "pkg/a.py"]


def test_taskfile_uses_a_fresh_session_not_the_start_packs(tmp_path):
    started = {"task": {"id": "t1", "generation": 3, "workspace_path": str(tmp_path)}}
    tf = av_container.write_taskfile(started, start_session="oe-start-abc")
    data = json.loads((tmp_path / ".av-task").read_text())
    assert data == tf
    assert data["task"] == "t1" and data["generation"] == 3 and data["agent"] == "claude-code"
    assert data["session"] and data["session"] != "oe-start-abc" and "oe-start" not in data["session"]


def test_start_body_matches_the_bench_request():
    body = av_container.start_body("app", "Fix it", "the goal", "oe-start-1")
    assert body == {"repo": "app", "title": "Fix it", "goal": "the goal", "agent": "claude-code",
                    "session": "oe-start-1", "pack_mode": "full"}


def test_release_tarball_is_checked_against_the_pinned_sha(tmp_path, monkeypatch):
    monkeypatch.setenv("OE_CACHE", str(tmp_path))
    bad = tmp_path / f"{av_settings.TARBALL}.tar.gz"
    bad.write_bytes(b"not the release")
    with pytest.raises(RuntimeError, match="sha256"):
        av_settings.release_tarball(download=lambda url, dest: None)
    assert not bad.exists()  # a bad cached file is removed so the next run downloads again


def test_fetch_preflight_fails_once_and_clearly_on_a_changed_release(tmp_path, monkeypatch, capsys):
    """Run before `harbor run` in CI, so a changed release stops the leg before any trial installs."""
    monkeypatch.setenv("OE_CACHE", str(tmp_path))
    monkeypatch.setattr(av_settings, "_urlretrieve", lambda url, dest: Path(dest).write_bytes(b"re-uploaded"))
    assert av_settings.main(["fetch"]) == 1
    err = capsys.readouterr().err
    assert "::error::" in err and av_settings.SHA256 in err and av_settings.AV_RELEASE in err


def test_fetch_preflight_passes_with_the_pinned_bytes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OE_CACHE", str(tmp_path))
    monkeypatch.setattr(av_settings, "SHA256", hashlib.sha256(b"the release").hexdigest())
    monkeypatch.setattr(av_settings, "_urlretrieve", lambda url, dest: Path(dest).write_bytes(b"the release"))
    assert av_settings.main(["fetch"]) == 0
    assert capsys.readouterr().out.strip().endswith(".tar.gz")


def test_download_goes_to_a_private_part_file(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setenv("OE_CACHE", str(tmp_path))
    monkeypatch.setattr(av_settings, "SHA256", hashlib.sha256(b"x").hexdigest())
    av_settings.release_tarball(download=lambda url, dest: (seen.append(Path(dest).name), Path(dest).write_bytes(b"x")))
    (name,) = seen
    assert name.endswith(".part") and name != f"{av_settings.TARBALL}.tar.part"  # unique per process
    assert not list(tmp_path.glob("*.part"))


def test_fetch_preflight_reports_a_failed_download_and_leaves_no_part_file(tmp_path, monkeypatch, capsys):
    def offline(url, dest):
        Path(dest).write_bytes(b"half")
        raise OSError("connection reset")
    monkeypatch.setenv("OE_CACHE", str(tmp_path))
    monkeypatch.setattr(av_settings, "_urlretrieve", offline)
    assert av_settings.main(["fetch"]) == 1
    err = capsys.readouterr().err
    assert "::error::" in err and "connection reset" in err and "could not download" in err
    assert not list(tmp_path.iterdir())


def test_two_downloads_use_different_part_files(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setenv("OE_CACHE", str(tmp_path))
    monkeypatch.setattr(av_settings, "SHA256", hashlib.sha256(b"x").hexdigest())
    for _ in range(2):
        av_settings.release_tarball(download=lambda url, dest: (seen.append(Path(dest).name), Path(dest).write_bytes(b"x")))
        (tmp_path / f"{av_settings.TARBALL}.tar.gz").unlink()
    assert len(set(seen)) == 2


def test_glibc_check():
    assert av_settings.glibc_ok("ldd (Debian GLIBC 2.41-12) 2.41")
    assert av_settings.glibc_ok("ldd (GNU libc) 2.39")
    assert not av_settings.glibc_ok("ldd (Debian GLIBC 2.36-9+deb12u10) 2.36")
    assert not av_settings.glibc_ok("musl libc (x86_64)")


# --- the Harbor subclass (only where Harbor is installed: `uv sync --extra run`) ---------------

def test_harbor_agent_options_and_settings(tmp_path):
    pytest.importorskip("harbor")
    from oe_agents.claude_code_av import ClaudeCodeAv

    ClaudeCodeAv.parse_options({"av_hook_budget": 600, "av_jit_hooks": False, "max_turns": 40}, {})
    with pytest.raises(Exception, match="(?i)unknown"):
        ClaudeCodeAv.parse_options({"scholion_version": "x"}, {})
    a = ClaudeCodeAv(logs_dir=tmp_path, model_name="anthropic/deepseek-flash", av_hook_budget=600)
    assert ClaudeCodeAv.name() == "claude-code"
    assert "--budget 600" in a.config_source["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert set(a.config_source["hooks"]) == {"SessionStart", "PostToolUse", "PreToolUse", "Stop"}
    with pytest.raises(ValueError, match="av_version"):
        ClaudeCodeAv(logs_dir=tmp_path, model_name="anthropic/deepseek-flash", av_version="release/9.9.9")


def test_finish_against_a_stub_daemon(tmp_path, monkeypatch):
    # /healthz answers plain text; GET /v1/tasks/{id} nests the task under "task"
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/healthz":
                return self._send(200, "ok", "text/plain")
            if self.path == "/v1/tasks/t1":
                return self._send(200, json.dumps({"task": {"id": "t1", "status": "review"}, "record_count": 1}))
            if self.path == "/v1/tasks/t1/records":
                return self._send(200, json.dumps({"records": [{"kind": "decision", "summary": "s"}]}))
            self._send(404, "{}")

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            ok = self.path == "/v1/tasks/t1/checkpoint" and self.headers.get("X-Av-Generation") == "2"
            self._send(200 if ok else 409, "{}")

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(av_container, "AV_URL", f"http://127.0.0.1:{srv.server_port}")
        (tmp_path / "task.json").write_text(json.dumps({"id": "t1", "generation": 2}))
        av_container.main(["finish", "--out", str(tmp_path)])
    finally:
        srv.shutdown()
    fin = json.loads((tmp_path / "finish.json").read_text())
    assert fin["checkpoint_ok"] is True and fin["healthz"] == "ok"
    assert fin["task_status"] == "review" and fin["record_count"] == 1


# --- the handoff successor's records channel (oe_agents.handoff_b) -------------------------------

def _repo_with_uncommitted_work(tmp_path):
    """/app as the records channel's image has it: the base commit, A's patch applied on top."""
    app = tmp_path / "app"
    (app / "pkg").mkdir(parents=True)
    (app / "pkg" / "a.py").write_bytes(b"x = 1\n")
    (app / "b.txt").write_bytes(b"b\n")
    _git(app, "-c", "core.autocrlf=false", "init", "-q")
    _git(app, "config", "core.autocrlf", "false")
    _git(app, "add", "-A")
    _git(app, "commit", "-qm", "base")
    ws = tmp_path / "ws"
    (ws / "pkg").mkdir(parents=True)
    (ws / "pkg" / "a.py").write_bytes(b"x = 1\n")
    (ws / "b.txt").write_bytes(b"b\n")
    patch = ("diff --git a/pkg/a.py b/pkg/a.py\n--- a/pkg/a.py\n+++ b/pkg/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
             "diff --git a/pkg/new.py b/pkg/new.py\nnew file mode 100644\n--- /dev/null\n+++ b/pkg/new.py\n"
             "@@ -0,0 +1 @@\n+y = 3\n")
    (tmp_path / "a.patch").write_bytes(patch.encode())
    subprocess.run(["git", "-C", str(app), "apply", str(tmp_path / "a.patch")], check=True)
    return app, ws


def test_tree_matches_at_a_rev_ignores_uncommitted_work(tmp_path):
    app, ws = _repo_with_uncommitted_work(tmp_path)
    assert av_container.tree_matches(app, ws) == ["pkg/a.py"]  # the working tree has A's edit
    assert av_container.tree_matches(app, ws, "HEAD") == []


def test_records_to_post_drops_the_intent_and_superseded_records():
    data = {"records": [
        {"kind": "intent", "summary": "the goal", "created_at": "1"},
        {"kind": "attempt", "summary": "tried summing", "body": "b", "created_at": "3",
         "anchors": [{"path": "p.py", "symbol": "f", "extra": 1}, {"symbol": "nopath"}]},
        {"kind": "decision", "summary": "old", "superseded_by": "r9", "created_at": "2"},
        {"kind": "note", "summary": "x" * 300, "created_at": "2"},
    ]}
    bodies = av_container.records_to_post(data)
    assert [b["kind"] for b in bodies] == ["note", "attempt"]  # by created_at
    assert bodies[0]["summary"] == "x" * 200
    assert bodies[1] == {"kind": "attempt", "summary": "tried summing", "body": "b",
                         "anchors": [{"path": "p.py", "symbol": "f"}], "agent": "agent-a"}
    assert av_container.records_to_post({"records": [{"kind": "intent", "summary": "g"}]}) == []


def test_adopt_against_a_stub_daemon(tmp_path, monkeypatch):
    import http.server
    import threading

    app, ws = _repo_with_uncommitted_work(tmp_path)
    posted = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send(200, {"task": {"id": "t1"}, "changed": [{"path": "pkg/a.py"}, {"path": "pkg/new.py"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            posted.append((self.path, self.headers.get("X-Av-Generation"), body))
            self._send(200, {})

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out = tmp_path / "log"
    out.mkdir()
    (out / "task.json").write_text(json.dumps({"id": "t1", "generation": 2}))
    recs = tmp_path / "records.json"
    recs.write_text(json.dumps({"records": [{"kind": "intent", "summary": "g"},
                                            {"kind": "attempt", "summary": "s", "anchors": [{"path": "pkg/a.py"}]}]}))
    try:
        monkeypatch.setattr(av_container, "AV_URL", f"http://127.0.0.1:{srv.server_port}")
        av_container.main(["adopt", "--ws", str(ws), "--app", str(app), "--patch", str(tmp_path / "a.patch"),
                           "--records", str(recs), "--out", str(out)])
    finally:
        srv.shutdown()
    assert av_container.tree_diff(app, ws) == []
    assert (ws / "pkg" / "new.py").read_bytes() == b"y = 3\n"
    diff = subprocess.run(["git", "-C", str(ws), "diff", "--stat"], check=True, capture_output=True, text=True).stdout
    assert "pkg/a.py" in diff  # B sees A's changes with git diff, as in every channel
    assert [(p, g) for p, g, _ in posted] == [("/v1/tasks/t1/records", "2"), ("/v1/tasks/t1/checkpoint", "2")]
    assert posted[0][2]["agent"] == "agent-a" and posted[0][2]["kind"] == "attempt"
    adopt = json.loads((out / "adopt.json").read_text())
    assert adopt["records_posted"] == 1 and adopt["changed"] == ["pkg/a.py", "pkg/new.py"]
    assert adopt["git_diff"] == ["pkg/a.py"]  # tracked files only, as `git diff` shows them


def test_adopt_refuses_a_workspace_that_does_not_end_up_equal_to_app(tmp_path):
    app, ws = _repo_with_uncommitted_work(tmp_path)
    (app / "stray.txt").write_bytes(b"not in the patch\n")
    out = tmp_path / "log"
    out.mkdir()
    (out / "task.json").write_text(json.dumps({"id": "t1", "generation": 1}))
    (tmp_path / "r.json").write_text("{}")
    with pytest.raises(SystemExit, match="differs"):
        av_container.main(["adopt", "--ws", str(ws), "--app", str(app), "--patch", str(tmp_path / "a.patch"),
                           "--records", str(tmp_path / "r.json"), "--out", str(out)])


def test_changed_paths_reads_strings_or_objects():
    assert av_container.changed_paths({"changed": ["b", {"path": "a"}]}) == ["a", "b"]
    assert av_container.changed_paths("oops") == []
