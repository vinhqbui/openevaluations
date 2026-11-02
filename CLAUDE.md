# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

openevaluations: open, longitudinal evaluations of coding-agent CLIs, published at
openevaluations.si. It has a results schema (`schema/`, oe/1), a Python tool `oe` (`tools/oe/`),
Harbor task sets (`datasets/`), published runs (`runs/`) and a static site (`site/`). Agents run
through Harbor (`uv sync --extra run`, needs Docker; Harbor runs natively on Windows here).
The plan and phases: `README.md` "Status".

## Commands

```bash
uv sync                       # add --extra run for Harbor
uv run pytest -q              # all green before any commit
uv run oe validate            # runs/ against schema/
uv run oe detect && uv run oe site   # after adding a run: flags, then site/data
uv run oe site --check        # CI: site/data matches runs/
uv run python tools/gen/tallyho.py [--check]   # regenerate datasets/tallyho-cold
```

On Windows set `PYTHONUTF8=1` before `harbor run` (its console output is UTF-8).

The Scholion arm (`agents/oe_agents/`) needs `PYTHONPATH=<repo>/agents` for `harbor run -a
oe_agents.claude_code_av:ClaudeCodeAv`, and `--agent-setup-timeout-multiplier 2`. Claude Code on
DeepSeek: `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`, `ANTHROPIC_AUTH_TOKEN` = the
DeepSeek key, `ANTHROPIC_API_KEY` unset, `-m anthropic/deepseek-flash`, and `--ae` the haiku,
small-fast and subagent aliases to `deepseek-flash` (see `.github/workflows/tracker.yml`).
`agents/oe_agents/av_settings.py` pins the Scholion release by sha256; bump both together.

## Rules

- TDD: failing test first (`tools/tests/`), then code.
- `runs/*.jsonl` are append-only data. Fix a bad run by superseding it with a new file and
  saying why in its `notes`, never by editing published numbers. `oe detect` may rewrite `flags`.
- `site/data/` is generated: never edit by hand; rerun `oe site`.
- `datasets/tallyho-cold/` is generated from `datasets/_shared/`: edit the generator or the
  shared inputs. The image must never contain the fix (`solution/`) or hidden test (`tests/`).
- Only `harbor run` with a real agent spends money. Pre-register paid comparisons
  (`docs/PREREG-template.md`). Never commit `jobs/` (trajectories go to Actions artifacts).
- No significance claim below 30 valid sessions per cell; every cost carries its `cost_source`.
- Scholion is one evaluated arm, never the only subject. Code flows from scholion as data
  (`oe import-scholion`) and release binaries only; no proprietary agentvcs code here.
- `main` is protected: branch, PR, CI green. Data files with `.sh` need the executable bit in git
  (`git add --chmod=+x`), since Windows checkouts do not keep it.
