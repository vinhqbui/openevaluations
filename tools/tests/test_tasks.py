"""The tallyho task sets: every task's hidden test fails on the base tree and passes with its fix."""

import importlib.util
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from oe import REPO

TALLYHO = REPO / "datasets" / "_shared" / "tallyho"
SPECS = sorted((TALLYHO / "tasks").glob("*.toml")) + sorted((TALLYHO / "tasks-more").glob("*.toml"))


def _gen(name):
    spec = importlib.util.spec_from_file_location(f"gen_{name}", REPO / "tools" / "gen" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_tracker_set_is_still_the_four_tasks_and_the_more_set_is_separate(tmp_path):
    gen = _gen("tallyho")
    assert gen.generate(tmp_path / "cold") == ["compound-discounts", "csv-escaping", "paginated-scan",
                                                "summarize-abbrev"]
    more = gen.generate(tmp_path / "more", gen.SHARED / "tasks-more", gen.README_MORE)
    assert more == ["config-literal-values", "order-price-snapshot"]
    assert "tallyho-more" in (tmp_path / "more" / "README.md").read_text()
    assert not set(more) & {p.name for p in (tmp_path / "cold").iterdir()}


def _run_suite(app, hidden):
    shutil.copyfile(hidden, app / "tests" / hidden.name)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], cwd=app,
                       capture_output=True, text=True)
    (app / "tests" / hidden.name).unlink()
    return r.returncode


@pytest.mark.parametrize("spec_path", SPECS, ids=lambda p: p.stem)
def test_hidden_test_fails_on_the_base_and_passes_with_the_fix(tmp_path, spec_path):
    spec = tomllib.loads(spec_path.read_text(encoding="utf-8"))
    (hidden,) = spec["local_tests"]
    hidden = spec_path.parent / hidden["source"]
    fix = TALLYHO / "fixes" / f"{spec['fix_rev'].removeprefix('fix-')}.patch"
    app = tmp_path / "app"
    shutil.copytree(TALLYHO / "src", app)
    assert _run_suite(app, hidden) != 0, "the hidden test passes on the base tree"
    subprocess.run(["git", "init", "-q"], cwd=app, check=True)
    subprocess.run(["git", "apply", "--whitespace=nowarn", str(fix)], cwd=app, check=True)
    assert _run_suite(app, hidden) == 0, "the fix does not pass the whole suite"
    touched = sorted({l[6:].strip() for l in fix.read_text(encoding="utf-8").splitlines() if l.startswith("+++ b/")})
    assert touched == sorted(spec["relevant_files"])


def test_handoff_generator_finds_specs_in_both_task_sets():
    gen = _gen("handoff")
    for name in ("compound-discounts", "order-price-snapshot"):
        spec, test_name, hidden, fix = gen._spec(name)
        assert spec["name"] == name and hidden.exists() and fix.exists()
