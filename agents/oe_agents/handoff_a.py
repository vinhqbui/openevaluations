"""Predecessor A of the handoff benchmark's interrupt family, as a Harbor agent.

    PYTHONPATH=agents harbor run -p datasets/tallyho-cold -a oe_agents.handoff_a:HandoffA \
        -m anthropic/deepseek-flash -k 1 --ak max_turns=<cut> ...

Claude Code on the Scholion framework (ClaudeCodeAv) with two changes: the instruction asks it to
keep NOTES.md as it goes, and after the run, cut or not, /app is tarred into
/logs/agent/freeze/workspace.tar.gz. `oe freeze <job> --cut-turns <cut>` then writes one frozen A
per task, and tools/gen/handoff.py builds the channel tasks from it. The cut is Claude Code's own
`--max-turns`, so it is required.
"""

from typing import override

from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from oe_agents.claude_code_av import ClaudeCodeAv
from oe_agents.handoff_settings import freeze_command, predecessor_instruction


class HandoffA(ClaudeCodeAv):
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
