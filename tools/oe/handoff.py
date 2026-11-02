"""The handoff benchmark: freeze predecessor A, render its trace, and check for leaks.

A frozen A is one directory per task (`datasets/_shared/handoff/<family>/<task>/`):

    a.json            who A was, where it was cut, what it left, validity, sha256 of the rest
    workspace.patch   A's working tree against the base tree, NOTES.md excluded (git-style diff)
    NOTES.md          A's notes                                    -> the notes channel
    trajectory.json   A's ATIF trajectory, rendered to trace.md    -> the trace channel
    records.json      A's Scholion records (GET /v1/tasks/{id}/records) -> the records channel

Every channel task applies the same workspace.patch (repo-only is just that), so only what is
added on top differs. tools/gen/handoff.py turns frozen A's into Harbor tasks.
"""

import difflib
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

CHANNELS = ("repo-only", "trace", "notes", "records")
# The records channel needs B's daemon seeded with A's records; until that lands it is not generated.
BUILT_CHANNELS = ("repo-only", "trace", "notes")
SKIP_DIRS = {".git", ".jj", "__pycache__", ".pytest_cache"}
SKIP_FILES = {".av-task"}
NOTES = "NOTES.md"
MIN_MARKER = 20  # shorter lines (`return total`, `import pytest`) match too much to mean a leak
TRACE_MAX_CHARS = 4000


def _skipped(rel):
    parts = rel.split("/")
    return (any(p in SKIP_DIRS for p in parts[:-1]) or parts[-1] in SKIP_FILES or rel == NOTES
            or rel.endswith((".pyc", ".pyo")))


def read_tree(root):
    """{posix relpath: bytes} of the files under root, without VCS dirs, caches or the root NOTES.md."""
    root = Path(root)
    return {rel: p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and not _skipped(rel := p.relative_to(root).as_posix())}


def _lines(data):
    return data.decode("utf-8").splitlines(keepends=True)


def diff_trees(base, new):
    """A git-style unified diff from tree `base` to tree `new` (both {relpath: bytes})."""
    out = []
    for rel in sorted(set(base) | set(new)):
        a, b = base.get(rel), new.get(rel)
        if a == b:
            continue
        old = _lines(a) if a is not None else []
        cur = _lines(b) if b is not None else []
        body = list(difflib.unified_diff(old, cur, "a/" + rel if a is not None else "/dev/null",
                                         "b/" + rel if b is not None else "/dev/null", n=3))
        head = [f"diff --git a/{rel} b/{rel}\n"]
        if a is None:
            head.append("new file mode 100644\n")
        elif b is None:
            head.append("deleted file mode 100644\n")
        for line in body:
            # difflib leaves a final line without "\n" unterminated; git wants the marker
            out_line = line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
            head.append(out_line)
        out += head
    return "".join(out)


def patch_files(patch):
    """The paths a diff_trees patch touches."""
    return sorted({m.group(1) for m in re.finditer(r"^diff --git a/(\S+) b/", patch, re.M)})


# --- the trace channel ---------------------------------------------------------------------------

def _text(msg):
    if msg is None:
        return ""
    if isinstance(msg, str):
        return msg
    return "\n".join(p.get("text") or "[image omitted]" for p in msg if isinstance(p, dict))


def _cut(text, max_chars):
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n[... {len(text) - max_chars} more characters]"


def render_trace(traj, max_chars=TRACE_MAX_CHARS):
    """A's ATIF trajectory as markdown: every step's message, tool calls and (truncated) output."""
    out = ["# Session transcript of the previous agent", ""]
    for s in traj.get("steps", []):
        who = {"user": "User", "agent": "Agent", "system": "System"}.get(s.get("source"), s.get("source"))
        out.append(f"## {s.get('step_id')}. {who}")
        msg = _text(s.get("message")).strip()
        if msg:
            out += ["", _cut(msg, max_chars)]
        for tc in s.get("tool_calls") or []:
            # A's actions in full (its edits are the point); only messages and outputs are cut
            args = json.dumps(tc.get("arguments"), ensure_ascii=False, sort_keys=True)
            out += ["", f"Tool call `{tc.get('function_name')}`:", "", "```json", args.replace("```", "'''"), "```"]
        for r in (s.get("observation") or {}).get("results") or []:
            out += ["", "Output:", "", "```", _cut(_text(r.get("content")), max_chars).replace("```", "'''"), "```"]
        out.append("")
    return "\n".join(out)


# --- the leak check -------------------------------------------------------------------------------

def _base_text(base):
    return "\n".join(v.decode("utf-8", "replace") for v in base.values())


def leak_markers(hidden_tests, fix_patch, base):
    """Strings that must not reach a frozen artifact: {"hidden_test": [...], "fix": [...]}.

    Hidden test: its file stem, its test function names, and its lines of MIN_MARKER chars or
    more. Fix: the patch's added lines of MIN_MARKER chars or more. Anything already in the base
    tree is dropped, since A reads the base tree and a trace quoting it is not a leak.
    """
    text = _base_text(base)

    def keep(xs):
        return sorted({x for x in xs if len(x) >= MIN_MARKER and x not in text})

    hidden = set()
    for name, body in hidden_tests.items():
        hidden.add(Path(name).stem)
        hidden |= {n for n in re.findall(r"def (test_\w+)", body) if n not in text}
        hidden |= set(keep(ln.strip() for ln in body.splitlines()))
    fix = keep(ln[1:].strip() for ln in fix_patch.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    return {"hidden_test": sorted(hidden), "fix": fix}


def find_leaks(artifacts, markers):
    """[{artifact, kind, marker}] for every marker found in an artifact's text."""
    found = []
    for name, text in sorted(artifacts.items()):
        for kind in ("hidden_test", "fix"):
            for m in markers[kind]:
                if m in text:
                    found.append({"artifact": name, "kind": kind, "marker": m})
    return found


# --- oe freeze --------------------------------------------------------------------------------------

def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _untar(data):
    tree = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            rel = m.name.removeprefix("./")
            tree[rel] = tf.extractfile(m).read()
    return tree


def _cli_result(agent_dir):
    p = agent_dir / "claude-code.txt"
    res = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("type") == "result":
                res = d
    return res


def _is_text(data):
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return b"\0" not in data


def _records(data):
    try:
        rec = json.loads(data)
    except ValueError:
        return 0
    rows = rec.get("records", rec) if isinstance(rec, dict) else rec
    return len(rows) if isinstance(rows, list) else 0


def freeze(trial_dir, out_dir, cut_turns, base_src=None):
    """Freeze one A trial into out_dir/<task>/ and return its a.json (with `valid` and `problems`)."""
    from . import REPO

    trial_dir = Path(trial_dir)
    base_src = Path(base_src or REPO / "datasets" / "_shared" / "tallyho" / "src")
    result = json.loads((trial_dir / "result.json").read_text(encoding="utf-8"))
    task = result["task_name"].split("/")[-1]
    agent_dir = trial_dir / "agent"
    problems = []

    tar = agent_dir / "freeze" / "workspace.tar.gz"
    ws = _untar(tar.read_bytes()) if tar.exists() else None
    if ws is None:
        problems.append("no workspace.tar.gz (the freeze step did not run)")
        ws = {}
    notes = ws.get(NOTES, b"")
    tree = {k: v for k, v in ws.items() if not _skipped(k)}
    binary = sorted(k for k, v in tree.items() if not _is_text(v))
    tree = {k: v for k, v in tree.items() if k not in binary}
    patch = diff_trees(read_tree(base_src), tree) if tar.exists() else ""
    traj = (agent_dir / "trajectory.json").read_bytes() if (agent_dir / "trajectory.json").exists() else b""
    recs = (agent_dir / "scholion" / "records.json").read_bytes() if (agent_dir / "scholion" / "records.json").exists() else b""

    if not notes.strip():
        problems.append("A left no NOTES.md (or an empty one)")
    if tar.exists() and not patch:
        problems.append("A changed no file besides NOTES.md")
    if not traj:
        problems.append("no trajectory.json")
    if _records(recs) == 0:
        problems.append("A left no Scholion records")
    reward = ((result.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    if reward is not None and float(reward) >= 1.0:
        problems.append("A already passed the hidden tests when it was cut")
    invalid = ((result.get("agent_result") or {}).get("metadata") or {}).get("oe_invalid")
    if invalid:  # docs/PREREG-tracker-av.md's validity rules hold for A too
        problems.append(f"A's av session invalid: {invalid}")
    if result.get("exception_info"):
        problems.append(f"A's trial raised {result['exception_info'].get('exception_type')}")

    info = result.get("agent_info") or {}
    cli = _cli_result(agent_dir)
    files = {"workspace.patch": patch.encode("utf-8"), NOTES: notes, "trajectory.json": traj, "records.json": recs}
    a = {
        "task": task, "cut_turns": cut_turns, "a_turns": cli.get("num_turns"), "a_stop": cli.get("subtype"),
        "agent": {"name": info.get("name"), "version": info.get("version")},
        "model": (info.get("model_info") or {}).get("name"),
        "a_reward": reward,
        "trial_name": result.get("trial_name"), "started_at": result.get("started_at"),
        "files_changed": patch_files(patch), "binary_files_left_out": binary, "records": _records(recs),
        "sha256": {k: _sha(v) for k, v in sorted(files.items())},
        "valid": not problems, "problems": problems,
    }
    d = Path(out_dir) / task
    d.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (d / name).write_bytes(data)
    (d / "a.json").write_text(json.dumps(a, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return a
