"""Reads ATIF trajectories (Harbor's agent/trajectory.json) for call counts and dead-end matching."""

import fnmatch
import json
import re
from pathlib import Path

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "edit", "write", "apply_patch"}


def load(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None


def llm_calls(traj):
    fm = traj.get("final_metrics") or {}
    for k in ("llm_call_count", "total_steps"):
        if isinstance(fm.get(k), int):
            return fm[k]
    return sum(1 for s in traj.get("steps", []) if s.get("source") == "agent")


def tool_calls(traj):
    return sum(len(s.get("tool_calls") or []) for s in traj.get("steps", []))


def _args(tc):
    a = tc.get("arguments")
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except ValueError:
            return {}
    return a if isinstance(a, dict) else {}


def written_texts(traj):
    """(path, text) for every edit or write: Edit.new_string, Write.content, MultiEdit edits.

    old_string never counts, as in scholion-bench's metrics.rs.
    """
    out = []
    for s in traj.get("steps", []):
        for tc in s.get("tool_calls") or []:
            if tc.get("function_name") not in EDIT_TOOLS:
                continue
            a = _args(tc)
            path = a.get("file_path") or a.get("path") or ""
            if "new_string" in a:
                out.append((path, a["new_string"]))
            if "content" in a:
                out.append((path, a["content"]))
            for e in a.get("edits") or []:
                if isinstance(e, dict) and "new_string" in e:
                    out.append((path, e["new_string"]))
    return out


def _glob_match(path, pattern):
    # file_glob may be "{a,b,c}" as in scholion task specs
    pats = pattern[1:-1].split(",") if pattern.startswith("{") and pattern.endswith("}") else [pattern]
    p = path.replace("\\", "/")
    return any(fnmatch.fnmatch(p, g) or p.endswith("/" + g) for g in pats)


def repeated_dead_ends(traj, dead_ends):
    """Number of edit calls whose new text matches a dead end's pattern on a matching file."""
    n = 0
    compiled = [(d["file_glob"], re.compile(d["pattern"])) for d in dead_ends]
    for path, text in written_texts(traj):
        if any(_glob_match(path, g) and rx.search(text or "") for g, rx in compiled):
            n += 1
    return n
