import json
import shutil
from pathlib import Path

import pytest

from oe import schema
from oe.import_scholion import convert_dir, import_tree

FIX = Path(__file__).parent / "fixtures"


def make_results(tmp_path):
    root = tmp_path / "results"
    for name, rows, meta in [
        ("2026-10-27-haiku/04-final-shipped-av", "av-rows.jsonl", "base-meta.json"),
        ("2026-10-29-relay-cold-pilot", "relay-rows.jsonl", "relay-meta.json"),
    ]:
        d = root / name
        d.mkdir(parents=True)
        shutil.copy(FIX / rows, d / "rows.jsonl")
        shutil.copy(FIX / meta, d / "meta.json")
    # a retrieval result dir: rows without "arm" must be skipped
    r = root / "2026-10-27-haiku/e1-retrieval-main"
    r.mkdir(parents=True)
    (r / "rows.jsonl").write_text('{"task":"x","method":"pack","budget":2000}\n')
    (r / "meta.json").write_text('{"budgets":[2000]}')
    return root


def test_import_tree_writes_one_valid_file_per_agent_run(tmp_path):
    out = tmp_path / "runs"
    written = import_tree(make_results(tmp_path), out)
    assert sorted(p.name for p in written) == [
        "scholion-2026-10-27-haiku-04-final-shipped-av.jsonl",
        "scholion-2026-10-29-relay-cold-pilot.jsonl",
    ]
    for p in written:
        assert schema.validate_file(p) == []


def test_convert_maps_fields(tmp_path):
    root = make_results(tmp_path)
    run, ss = convert_dir(root / "2026-10-29-relay-cold-pilot", run_id="x")
    assert run["agent"] == {"name": "claude-code", "version": "2.1.312"}
    assert run["model"] == {"provider": "deepseek", "name": "deepseek-flash"}
    assert run["dataset"]["name"] == "scholion-relay"
    assert run["date"] == "2026-10-29T04:31:00Z"
    assert run["config"]["arms"] == ["cold"]
    skipped = [s for s in ss if s["status"] == "skipped"]
    assert len(skipped) == 11
    ok = [s for s in ss if s["status"] == "ok"][0]
    assert ok["cost_source"] in ("estimated", "capped")
    assert ok["tokens_billed"] > 0 and ok["reward"] in (0.0, 1.0)


def test_validate_rejects_bad_files(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text(json.dumps({"type": "session", "run_id": "x"}) + "\n")
    assert schema.validate_file(p)  # first line must be the run

    root = make_results(tmp_path)
    good = import_tree(root, tmp_path / "runs")[0]
    lines = good.read_text().splitlines()
    run = json.loads(lines[0])
    run["dataset"]["visibility"] = "private"
    p.write_text("\n".join([json.dumps(run)] + lines[1:]) + "\n")
    errs = schema.validate_file(p)
    assert any("private" in e for e in errs)

    s = json.loads(lines[1])
    s["run_id"] = "other"
    p.write_text("\n".join([lines[0], json.dumps(s)]) + "\n")
    assert any("run_id" in e for e in schema.validate_file(p))
