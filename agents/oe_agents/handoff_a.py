"""Predecessor A of the handoff benchmark, as a Harbor agent.

    PYTHONPATH=agents harbor run -p datasets/tallyho-cold -a oe_agents.handoff_a:HandoffA \
        -m anthropic/deepseek-flash -k 1 --ak max_turns=<cut> [--ak wrapup_turns=<n>] ...

Claude Code on the Scholion framework (ClaudeCodeAv) with these changes: the instruction asks it
to keep NOTES.md as it goes, and after the run, cut or not, /app is tarred into
/logs/agent/freeze/workspace.tar.gz. `oe freeze <job> --cut-turns <cut>` then writes one frozen A
per task, and tools/gen/handoff.py builds the channel tasks from it. The cut is Claude Code's own
`--max-turns`, so it is required.

With `wrapup_turns` (the cross-vendor family, docs/PREREG-handoff-xvendor.md), the session is
resumed once after the cut (`claude --continue`) with handoff_settings.WRAPUP_MESSAGE and at most
that many turns, inside the av task, so the av Stop hook can ask for records as it does when a
person ends a session. The tree at the cut is kept as workspace-cut.tar.gz and the cut's
stream-json as claude-code-cut.txt; its cost is added to the wrap-up's.
"""

import json
from typing import override

from harbor.agents.installed.claude_code import ClaudeCode
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from pydantic import Field

from oe_agents.claude_code_av import ClaudeCodeAv, ClaudeCodeAvOptions
from oe_agents.handoff_settings import WRAPUP_MESSAGE, freeze_command, predecessor_instruction

CUT_LOG = "claude-code-cut.txt"


class HandoffAOptions(ClaudeCodeAvOptions):
    wrapup_turns: int = Field(default=0, description="Turns of the wrap-up after the cut (0: none).")


def stream_result(text):
    """The last {"type": "result"} event of a Claude Code stream-json log, or {}."""
    res = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("type") == "result":
            res = d
    return res


class HandoffA(ClaudeCodeAv):
    options_model = HandoffAOptions
    options: HandoffAOptions

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.options.max_turns:
            raise ValueError("HandoffA needs max_turns (--ak max_turns=<cut>): the pre-registered cut")

    @override
    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        try:
            await super().run(predecessor_instruction(instruction), environment, context)
        finally:
            await self._quiet(environment, freeze_command(), timeout_sec=120)

    async def _claude_or_cap(self, instruction, environment, context):
        """One Claude Code run; reaching --max-turns is the cut, not a failure (Claude exits 1 then)."""
        try:
            await ClaudeCode.run(self, instruction, environment, context)
        except Exception:
            log = (self.environment_logs_dir / "claude-code.txt").as_posix()
            hit = await environment.exec(command=f"grep -Eq '\"subtype\": ?\"error_max_turns\"' {log}")
            if hit.return_code != 0:
                raise

    @override
    async def _run_claude(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        await self._claude_or_cap(instruction, environment, context)
        n = self.options.wrapup_turns
        if not n:
            return
        logs = self.environment_logs_dir.as_posix()
        await self._quiet(environment, freeze_command("workspace-cut"), timeout_sec=120)
        await self.exec_as_agent(environment, command=f"cp {logs}/claude-code.txt {logs}/{CUT_LOG}")
        cut = self.options.max_turns
        self.options.max_turns = n
        self._resume = True
        try:
            await self._claude_or_cap(WRAPUP_MESSAGE, environment, context)
        finally:
            self._resume = False
            self.options.max_turns = cut

    @override
    def populate_context_post_run(self, context: AgentContext) -> None:
        super().populate_context_post_run(context)
        p = self.logs_dir / CUT_LOG
        if not p.exists():
            return
        cut = stream_result(p.read_text(encoding="utf-8", errors="replace"))
        wrap = stream_result((self.logs_dir / "claude-code.txt").read_text(encoding="utf-8", errors="replace")
                             if (self.logs_dir / "claude-code.txt").exists() else "")
        # Claude Code's total_cost_usd after `--continue` is the whole session's (seen 2026-11-10:
        # the wrap-up's modelUsage holds the cut's tokens too), so it is already the A's cost; add
        # the cut's only when the wrap-up reports less than the cut, i.e. its own part alone.
        c, w = cut.get("total_cost_usd"), wrap.get("total_cost_usd")
        if context.cost_usd is not None and c is not None and w is not None and float(w) < float(c):
            context.cost_usd = float(context.cost_usd) + float(c)
        context.metadata = {**(context.metadata or {}), "a_cut_turns": cut.get("num_turns"),
                            "a_cut_cost_usd": cut.get("total_cost_usd"), "a_wrapup_turns": wrap.get("num_turns"),
                            "a_wrapup_cost_usd": wrap.get("total_cost_usd")}
