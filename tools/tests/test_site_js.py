"""site/js/oe.js helpers, run under node (skipped where node is not installed)."""

import json
import shutil
import subprocess

import pytest

from oe import REPO

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def oe_js(expr):
    """The JSON value of `expr`, evaluated with site/js/oe.js loaded as window.OE."""
    script = (
        "const vm = require('vm'), fs = require('fs');"
        "const ctx = {window: {}, document: {}}; vm.createContext(ctx);"
        f"vm.runInContext(fs.readFileSync({json.dumps(str(REPO / 'site' / 'js' / 'oe.js'))}, 'utf8'), ctx);"
        f"ctx.OE = ctx.window.OE; process.stdout.write(JSON.stringify(vm.runInContext({json.dumps(expr)}, ctx)));"
    )
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_version_label_never_doubles_the_v():
    # goose's row holds its release tag "v1.60.2"; the other CLIs' rows hold bare versions
    assert oe_js('["v1.60.2", "2.1.329", "1.19.6", "0.166.0", null].map(OE.version)') == \
        ["v1.60.2", "v2.1.329", "v1.19.6", "v0.166.0", "v?"]


def test_series_title_leads_with_the_model():
    s = '{dataset: "tallyho-cold", agent: "claude-code", model: "claude-haiku-5-5", runner: "harbor"}'
    assert oe_js(f"OE.seriesTitle({s}, 'cold')") == "claude-haiku-5-5 · tallyho-cold · claude-code cold · harbor"


def test_by_model_keeps_models_apart_newest_first():
    items = json.dumps([
        {"m": "deepseek-flash", "d": "2026-11-04", "id": 1},
        {"m": "claude-haiku-5-5", "d": "2026-11-20", "id": 2},
        {"m": "deepseek-flash", "d": "2026-11-02", "id": 3},
        {"m": "deepseek-v4-pro", "d": "2026-11-10", "id": 4},
    ])
    groups = oe_js(f"OE.byModel({items}, x => x.m, x => x.d).map(g => [g.model, g.items.map(x => x.id)])")
    assert groups == [["claude-haiku-5-5", [2]], ["deepseek-v4-pro", [4]], ["deepseek-flash", [1, 3]]]
