"""Runs inside the task container (python3, stdlib only): start the av task, then finish it.

    python3 oe_av.py start --title T --goal-env OE_AV_GOAL --base /app --repo app --out DIR [--base-rev HEAD]
    python3 oe_av.py adopt --ws WS --app /app --patch /handoff/a.patch --records /handoff/records.json --out DIR
    python3 oe_av.py finish --out DIR

`start` follows scholion-bench's `start_av_task`: the task is started over HTTP under a session
of its own (the start pack is kept only for the record), the workspace must hold the base tree
byte for byte, and `.av-task` gets a fresh session, so the agent's first SessionStart pack is a
full pack rather than back-references to the start pack.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

AV_URL = os.environ.get("AV_URL", "http://127.0.0.1:7420")
AGENT = "claude-code"
PREDECESSOR = "agent-a"  # the author of a handoff predecessor's records in the successor's daemon
ADOPT_SKIP = {".git", ".jj", ".av-task", "__pycache__", ".pytest_cache"}


def _call(method, path, body=None, generation=None, timeout=600):
    req = urllib.request.Request(AV_URL + path, method=method,
                                 data=None if body is None else json.dumps(body).encode())
    req.add_header("Content-Type", "application/json")
    if generation is not None:
        req.add_header("X-Av-Generation", str(generation))
    if os.environ.get("AV_TOKEN"):
        req.add_header("Authorization", "Bearer " + os.environ["AV_TOKEN"])
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8", "replace")
            if not text.strip():
                return r.status, None
            try:
                return r.status, json.loads(text)
            except ValueError:  # /healthz answers plain "ok"
                return r.status, text
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def start_body(repo, title, goal, session):
    return {"repo": repo, "title": title, "goal": goal, "agent": AGENT, "session": session, "pack_mode": "full"}


def _git_out(base, *args):
    return subprocess.run(["git", "-C", str(base), *args], check=True, capture_output=True).stdout


def tree_matches(base, ws, rev=None):
    """Tracked files of `base` that are missing from, or differ in, `ws` (sorted).

    With `rev`, each file is compared as committed at `rev` rather than as it is in base's working
    tree: the handoff successor's /app holds the predecessor's uncommitted work on top of HEAD.
    """
    if rev is None:
        names = sorted(p for p in _git_out(base, "ls-files", "-z").decode().split("\0") if p)
        want = {n: (lambda n=n: (Path(base) / n).read_bytes()) for n in names}
    else:
        want = {}
        for entry in (e for e in _git_out(base, "ls-tree", "-r", "-z", rev).decode().split("\0") if e):
            meta, _, name = entry.partition("\t")
            sha = meta.split()[2]
            want[name] = lambda sha=sha: _git_out(base, "cat-file", "blob", sha)
    bad = []
    for name in sorted(want):
        b = Path(ws) / name
        if not b.is_file() or want[name]() != b.read_bytes():
            bad.append(name)
    return bad


def _files(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): p for p in root.rglob("*")
            if p.is_file() and not ADOPT_SKIP & set(p.relative_to(root).parts)}


def tree_diff(a, b):
    """Paths whose bytes differ between trees `a` and `b`, or that only one has (VCS dirs, caches skipped)."""
    fa, fb = _files(a), _files(b)
    return sorted(n for n in set(fa) | set(fb)
                  if n not in fa or n not in fb or fa[n].read_bytes() != fb[n].read_bytes())


def records_to_post(data):
    """A predecessor's exported records as POST /v1/tasks/{id}/records bodies, authored by agent-a.

    Its intent is left out (the successor's task has the same goal, so its own intent says it),
    and so is anything a later record superseded. Anchors keep path and symbol.
    """
    rows = data.get("records", data) if isinstance(data, dict) else data
    rows = sorted((r for r in rows or [] if isinstance(r, dict)), key=lambda r: r.get("created_at") or "")
    out = []
    for r in rows:
        if r.get("kind") == "intent" or r.get("superseded_by"):
            continue
        anchors = [{k: a[k] for k in ("path", "symbol") if a.get(k)} for a in r.get("anchors") or []]
        out.append({"kind": r["kind"], "summary": (r.get("summary") or "")[:200], "body": r.get("body") or "",
                    "anchors": [a for a in anchors if a.get("path")], "agent": PREDECESSOR})
    return out


def write_taskfile(started, start_session):
    task = started["task"]
    tf = {"task": task["id"], "session": str(uuid.uuid4()), "generation": task.get("generation", 1), "agent": AGENT}
    assert tf["session"] != start_session
    Path(task["workspace_path"], ".av-task").write_text(json.dumps(tf), encoding="utf-8")
    return tf


def cmd_start(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    session = f"oe-start-{uuid.uuid4()}"
    status, started = _call("POST", "/v1/tasks", start_body(a.repo, a.title, os.environ[a.goal_env], session))
    if status // 100 != 2 or not isinstance(started, dict):
        sys.exit(f"av task start: HTTP {status}: {str(started)[:500]}")
    ws = Path(started["task"]["workspace_path"])
    (out / "start-pack.md").write_text((started.get("pack") or {}).get("markdown") or "", encoding="utf-8")
    bad = tree_matches(a.base, ws, a.base_rev)
    if bad:
        sys.exit(f"av workspace {ws} differs from {a.base} in {len(bad)} file(s): {bad[:5]}")
    tf = write_taskfile(started, session)
    task = started["task"]
    (out / "task.json").write_text(json.dumps({
        "id": task["id"], "slug": task.get("slug"), "generation": tf["generation"],
        "workspace_path": str(ws), "start_session": session, "session": tf["session"]}), encoding="utf-8")
    print(ws)


def changed_paths(task):
    """The paths of GET /v1/tasks/{id}'s `changed` (strings or {path} objects)."""
    changed = task.get("changed") if isinstance(task, dict) else None
    return sorted({c.get("path") if isinstance(c, dict) else c for c in changed or []} - {None})


def cmd_adopt(a):
    """The handoff successor's start: the predecessor's work and records, put into its av task.

    The task's workspace starts as the base commit. This copies /app's .git into it (so `git diff`
    shows the predecessor's changes, as in every other channel), applies the predecessor's patch,
    checks that the workspace now equals /app, posts the predecessor's records to the task and
    checkpoints. Any mismatch stops the trial before Claude starts.
    """
    out = Path(a.out)
    ws, app = Path(a.ws), Path(a.app)
    t = json.loads((out / "task.json").read_text(encoding="utf-8"))
    shutil.copytree(app / ".git", ws / ".git", symlinks=True)
    subprocess.run(["git", "-C", str(ws), "apply", "--whitespace=nowarn", str(Path(a.patch).resolve())],
                   check=True, capture_output=True)
    bad = tree_diff(app, ws)
    if bad:
        sys.exit(f"adopt: the workspace differs from {app} after the patch in {len(bad)} file(s): {bad[:5]}")
    posted = []
    for b in records_to_post(json.loads(Path(a.records).read_text(encoding="utf-8"))):
        status, body = _call("POST", f"/v1/tasks/{t['id']}/records", b, generation=t["generation"], timeout=120)
        if status // 100 != 2:
            sys.exit(f"adopt: record POST: HTTP {status}: {str(body)[:300]}")
        posted.append(b["kind"])
    status, body = _call("POST", f"/v1/tasks/{t['id']}/checkpoint", {}, generation=t["generation"], timeout=120)
    if status // 100 != 2:
        sys.exit(f"adopt: checkpoint: HTTP {status}: {str(body)[:300]}")
    status, task = _call("GET", f"/v1/tasks/{t['id']}", timeout=60)
    paths = changed_paths(task)
    if any(p == ".git" or p.startswith(".git/") for p in paths):
        sys.exit(f"adopt: the daemon snapshotted .git: {paths[:5]}")
    diff = subprocess.run(["git", "-C", str(ws), "diff", "--name-only"], capture_output=True, text=True).stdout
    (out / "adopt.json").write_text(json.dumps({"records_posted": len(posted), "kinds": posted,
                                                "changed": paths, "task_http": status,
                                                "git_diff": sorted(diff.split())}), encoding="utf-8")
    print(len(posted))


def _rss_kb():
    try:
        ps = subprocess.run(["ps", "-eo", "rss=,comm="], capture_output=True, text=True, timeout=10).stdout
        return sum(int(line.split()[0]) for line in ps.splitlines() if line.strip())
    except Exception:
        return None


def cmd_finish(a):
    out = Path(a.out)
    fin = {"checkpoint_ok": False}
    try:
        t = json.loads((out / "task.json").read_text(encoding="utf-8"))
        status, body = _call("POST", f"/v1/tasks/{t['id']}/checkpoint", {}, generation=t["generation"], timeout=120)
        fin.update(checkpoint_ok=status // 100 == 2, checkpoint_status=status)
        if status // 100 != 2:
            fin["checkpoint_error"] = str(body)[:500]
        status, task = _call("GET", f"/v1/tasks/{t['id']}", timeout=60)
        # GET /v1/tasks/{id} is {"task": {..., "status"}, "record_count", "changed", ...}
        fin["task_status"] = (task.get("task") or {}).get("status") if isinstance(task, dict) and status == 200 else status
        status, records = _call("GET", f"/v1/tasks/{t['id']}/records", timeout=60)
        if status == 200:
            (out / "records.json").write_text(json.dumps(records, indent=1), encoding="utf-8")
            rows = records.get("records", records) if isinstance(records, dict) else records
            fin["record_count"] = len(rows) if isinstance(rows, list) else None
    except Exception as e:  # finish is best-effort: whatever failed shows in finish.json
        fin["error"] = f"{type(e).__name__}: {e}"[:500]
    try:
        status, _ = _call("GET", "/healthz", timeout=10)
        fin["healthz"] = "ok" if status == 200 else status
    except Exception as e:
        fin["healthz"] = f"{type(e).__name__}: {e}"[:200]
    for name, key in (("up-secs", "up_secs"), ("daemon-restarted", "daemon_restarted")):
        p = out / name
        if p.exists():
            v = p.read_text().strip()
            fin[key] = int(v) if v.isdigit() else v
    fin["rss_kb"] = _rss_kb()
    fin["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (out / "finish.json").write_text(json.dumps(fin), encoding="utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(prog="oe_av")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--title", required=True)
    s.add_argument("--goal-env", required=True)
    s.add_argument("--base", default="/app")
    s.add_argument("--repo", default="app")
    s.add_argument("--out", required=True)
    s.add_argument("--base-rev", default=None, help="compare the workspace with base as committed at this rev")
    d = sub.add_parser("adopt")
    d.add_argument("--ws", required=True)
    d.add_argument("--app", default="/app")
    d.add_argument("--patch", required=True)
    d.add_argument("--records", required=True)
    d.add_argument("--out", required=True)
    f = sub.add_parser("finish")
    f.add_argument("--out", required=True)
    a = p.parse_args(argv)
    {"start": cmd_start, "adopt": cmd_adopt, "finish": cmd_finish}[a.cmd](a)


if __name__ == "__main__":
    main()
