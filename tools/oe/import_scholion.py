"""Imports scholion-bench results (bench/results/**/{rows.jsonl,meta.json}) as oe/1 run files.

One results directory becomes one run. Retrieval results (rows without an `arm`) are not agent
runs and are skipped. Transcripts were never committed, so trajectories are `none`.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import SCHEMA_VERSION, runfile

TALLYHO = {"compound-discounts", "csv-escaping", "paginated-scan", "summarize-abbrev"}


def _date(s):
    # "2026-10-27 10:05 UTC"
    d = datetime.strptime(s.replace(" UTC", ""), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _dataset(tasks):
    if all(t.startswith("relay-") for t in tasks):
        return "scholion-relay"
    if tasks <= TALLYHO:
        return "tallyho-cold"
    return "scholion-cold" if all(t.startswith("scholion-") for t in tasks) else "scholion-mixed"


def _provider(model):
    m = model.lower()
    for p in ("deepseek", "openai", "gpt", "grok", "gemini"):
        if p in m:
            return {"gpt": "openai", "grok": "xai", "gemini": "google"}.get(p, p)
    return "anthropic"


def convert_dir(d, run_id):
    d = Path(d)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    rows = [json.loads(l) for l in (d / "rows.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    tasks = {r["task"] for r in rows}
    arms = sorted({r["arm"] for r in rows})
    model = (meta.get("models") or ["unknown"])[0]
    provider = _provider(model)
    version = (meta.get("claude_version") or "").split(" ")[0] or None
    prereg = d / "PREREG.md"
    extra = {k: meta[k] for k in ("av_mcp", "hook_args") if k in meta}
    run = {
        "type": "run",
        "schema_version": SCHEMA_VERSION,
        "id": run_id,
        "date": _date(meta["date"]),
        "dataset": {"name": _dataset(tasks), "version": None, "rev": meta.get("av_rev"), "visibility": "public"},
        "agent": {"name": "claude-code", "version": version},
        "model": {"provider": provider, "name": model},
        "config": {"arm": arms[0] if len(arms) == 1 else "multi", "arms": arms,
                   "attempts_per_task": max((r.get("rep", 1) for r in rows), default=1)},
        "harness": {"runner": "scholion-bench", "scholion_rev": meta.get("av_rev"), "extra": extra},
        "machine": {"kind": "local", "os": None, "sandbox": None},
        "budget": None,
        "prereg": "PREREG.md" if prereg.exists() else None,
        "seed": meta.get("seed"),
        "flags": [],
        "source": None,
    }
    sessions = []
    for r in rows:
        m = r.get("metrics") or {}
        status = {"ok": "ok", "invalid": "invalid", "skipped_budget": "skipped"}.get(r["status"], "error")
        truncated = bool(m.get("truncated"))
        if status == "skipped":
            cost_source = "unavailable"
        elif truncated:
            cost_source = "capped"
        elif provider != "anthropic":
            # Claude Code cannot price non-Anthropic models; scholion-bench used --price-per-mtok
            cost_source = "estimated"
        else:
            cost_source = "measured"
        success = bool(r.get("success")) and status == "ok"
        sessions.append({
            "type": "session",
            "run_id": run_id,
            "task": r["task"],
            "arm": r["arm"],
            "attempt": int(r.get("rep", 1)),
            "status": status,
            "reason": r.get("reason"),
            "reward": 1.0 if success else 0.0,
            "accepted": success,
            "cost_usd": None if status == "skipped" else r.get("cost_usd"),
            "cost_source": cost_source,
            "tokens_billed": m.get("tokens_total"),
            "tokens_to_first_edit": m.get("tokens_to_first_edit"),
            "turns": m.get("turns"),
            "tool_calls": m.get("tool_calls"),
            "repeated_dead_ends": m.get("repeated_dead_ends"),
            "wall_secs": float(r.get("wall_secs", 0.0)),
            "truncated": truncated,
            "trajectory": {"kind": "none"},
        })
    return run, sessions


def _run_id(root, d):
    rel = d.relative_to(root).as_posix()
    return "scholion-" + re.sub(r"[^a-z0-9._-]+", "-", rel.lower()).strip("-")


def import_tree(root, out_dir, source_url=None):
    """Converts every agent-run directory under root; returns the files written."""
    root, out_dir = Path(root), Path(out_dir)
    written = []
    for rows in sorted(root.rglob("rows.jsonl")):
        d = rows.parent
        first = rows.read_text(encoding="utf-8").split("\n", 1)[0]
        if not (d / "meta.json").exists() or '"arm"' not in first:
            continue
        rid = _run_id(root, d)
        run, ss = convert_dir(d, rid)
        if source_url:
            run["source"] = f"{source_url.rstrip('/')}/{d.relative_to(root).as_posix()}"
        written.append(runfile.write(out_dir / f"{rid}.jsonl", run, ss))
    return written
