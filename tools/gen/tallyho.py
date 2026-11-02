"""Writes datasets/tallyho-cold/ and datasets/tallyho-more/ (Harbor tasks) from datasets/_shared/tallyho/.

tallyho-cold is the weekly tracker's four tasks (tasks/); tallyho-more is tasks written here
afterwards (tasks-more/), kept apart so the tracker's task set never changes under its series.

Idempotent: run it again after changing the shared sources; it rewrites every task directory.
Inputs are vendored from scholion bench/tallyho (src, fixes) and bench/tasks-tallyho (specs,
hidden tests). The image holds the base tree as one orphan commit, so no fix is in history;
the fix patch is only in solution/ and the hidden test only in tests/.

Usage: python tools/gen/tallyho.py [--check]
"""

import shutil
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SHARED = REPO / "datasets" / "_shared" / "tallyho"
OUT = REPO / "datasets" / "tallyho-cold"
OUT_MORE = REPO / "datasets" / "tallyho-more"
SOURCE = "https://github.com/vinhqbui/scholion/tree/main/bench/tasks-tallyho"
SOURCE_MORE = "https://github.com/vinhqbui/openevaluations/tree/main/datasets/_shared/tallyho/tasks-more"

DOCKERFILE = """\
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates procps \\
    && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir pytest==8.4.1 \\
    && useradd -m -s /bin/bash agent
COPY src/ /app/
RUN cd /app && git -c init.defaultBranch=main init -q \\
    && git -c user.name=oe -c user.email=oe@localhost add -A \\
    && git -c user.name=oe -c user.email=oe@localhost -c commit.gpgsign=false commit -qm "tallyho 0.4.0" \\
    && chown -R agent:agent /app
WORKDIR /app
"""

TEST_SH = """\
#!/bin/bash
# Copies the hidden test in and runs the whole suite; reward 1 when everything passes.
mkdir -p /logs/verifier
cp /tests/{test} /app/tests/{test}
cd /app && python -m pytest -q -p no:cacheprovider tests
status=$?
if [ "$status" -eq 0 ]; then echo 1 > /logs/verifier/reward.txt; else echo 0 > /logs/verifier/reward.txt; fi
exit 0
"""

SOLVE_SH = """\
#!/bin/bash
set -euo pipefail
cd /app && git apply --whitespace=nowarn /solution/fix.patch
"""

TASK_TOML = """\
schema_version = "1.4"
source = "{source}"

[task]
name = "openevaluations/{name}"
description = "tallyho: {name}"
keywords = ["python", "bugfix", "tallyho"]

[metadata]
relevant_files = {relevant}
max_turns = {max_turns}
dead_ends = []

[agent]
timeout_sec = 900
user = "agent"

[verifier]
timeout_sec = 180

[environment]
build_timeout_sec = 600
network_mode = "public"
cpus = 1
memory_mb = 2048
"""


def _toml_list(xs):
    return "[" + ", ".join(f'"{x}"' for x in xs) + "]"


def generate(out=OUT, tasks=None, readme=None):
    tasks = Path(tasks or SHARED / "tasks")
    more = tasks.name == "tasks-more"
    specs = sorted(tasks.glob("*.toml"))
    if out.exists():
        for d in out.iterdir():
            if d.is_dir():
                shutil.rmtree(d)
    out.mkdir(parents=True, exist_ok=True)
    names = []
    for spec_path in specs:
        spec = tomllib.loads(spec_path.read_text(encoding="utf-8"))
        name = spec["name"]
        fix = spec["fix_rev"].removeprefix("fix-")
        patch = SHARED / "fixes" / f"{fix}.patch"
        (hidden,) = spec["local_tests"]
        test_name = Path(hidden["path"]).name
        t = out / name
        (t / "environment").mkdir(parents=True)
        (t / "tests").mkdir()
        (t / "solution").mkdir()
        shutil.copytree(SHARED / "src", t / "environment" / "src")
        _w(t / "environment" / "Dockerfile", DOCKERFILE)
        _w(t / "instruction.md", spec["goal"].strip() + "\n")
        _w(t / "task.toml", TASK_TOML.format(name=name, source=SOURCE_MORE if more else SOURCE,
                                             relevant=_toml_list(spec["relevant_files"]),
                                             max_turns=spec.get("max_turns", 40)))
        shutil.copyfile(tasks / hidden["source"], t / "tests" / test_name)
        _w(t / "tests" / "test.sh", TEST_SH.format(test=test_name), exe=True)
        shutil.copyfile(patch, t / "solution" / "fix.patch")
        _w(t / "solution" / "solve.sh", SOLVE_SH, exe=True)
        names.append(name)
    _w(out / "README.md", (readme or README).format(tasks="\n".join(f"- `{n}`" for n in names)))
    return names


README = """\
# tallyho-cold

Four one-file bugs in tallyho, a 25-file Python shop library written for benchmarking (from
Scholion's `bench/tasks-tallyho`). One agent, cold start, hidden pytest file per task. Generated
by `tools/gen/tallyho.py`; do not edit the task directories by hand.

{tasks}

```bash
uv run harbor run -p datasets/tallyho-cold -a nop      # every reward 0
uv run harbor run -p datasets/tallyho-cold -a oracle   # every reward 1
uv run harbor run -p datasets/tallyho-cold -a claude-code -m anthropic/claude-haiku-5-5 -k 3 -o jobs
```
"""

README_MORE = """\
# tallyho-more

More one-file-or-two bugs in tallyho, written in openevaluations after the tracker's four
(`tallyho-cold`) and kept apart from them, so the weekly tracker's task set never changes. Same
base tree, same image, hidden pytest file per task. The handoff benchmark's interrupt family
uses them with the four. Generated by `tools/gen/tallyho.py`; do not edit by hand.

{tasks}

```bash
uv run harbor run -p datasets/tallyho-more -a nop      # every reward 0
uv run harbor run -p datasets/tallyho-more -a oracle   # every reward 1
```
"""

SETS = [(OUT, SHARED / "tasks", README), (OUT_MORE, SHARED / "tasks-more", README_MORE)]


def _w(p, text, exe=False):
    p.write_text(text, encoding="utf-8", newline="\n")
    if exe:
        p.chmod(0o755)


if __name__ == "__main__":
    if "--check" in sys.argv:
        import filecmp
        import tempfile

        stale = []
        for out, tasks, readme in SETS:
            with tempfile.TemporaryDirectory() as tmp:
                generate(Path(tmp), tasks, readme)
                diff = filecmp.dircmp(tmp, out)
                bad = diff.left_only + diff.right_only + diff.diff_files
                for sub in diff.subdirs.values():
                    bad += sub.left_only + sub.right_only + sub.diff_files
                stale += [f"{out.name}: {b}" for b in bad]
        if stale:
            print("generated tallyho datasets are stale:", stale)
            sys.exit(1)
        print("datasets/tallyho-cold and datasets/tallyho-more up to date")
    else:
        for out, tasks, readme in SETS:
            print("\n".join(generate(out, tasks, readme)))
