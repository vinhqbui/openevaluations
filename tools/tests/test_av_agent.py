"""The Scholion arm: Claude Code with av hooks, a daemon and a jj workspace, as a Harbor agent."""

import json
import subprocess

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
