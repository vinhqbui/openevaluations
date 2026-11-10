"""Successor B of the handoff benchmark's records channel: Claude Code on Scholion, given A's task.

    PYTHONPATH=agents harbor run -p datasets/handoff-<family> -i "*--records" \
        -a oe_agents.handoff_b:HandoffBAv -m anthropic/<model> --ak max_turns=40 ...

The records channel's image is the repo-only image (the base commit with A's patch applied,
uncommitted) plus /handoff/a.patch and /handoff/records.json. This is the tracker's `av` arm
(ClaudeCodeAv) with one step added between the av task start and the swap of /app
(av_container.py adopt): the task's workspace gets /app's .git and A's patch, so it equals /app
and `git diff` shows A's work as in every channel; A's records (all but its intent) are posted to
the task as agent-a's; and the task is checkpointed. /handoff is then deleted, so B reaches A's
records only through Scholion: the SessionStart pack and the pre-read hook.
"""

import shlex
from typing import ClassVar, override

from harbor.environments.base import BaseEnvironment

from oe_agents.av_settings import LOG
from oe_agents.claude_code_av import HELPER, ClaudeCodeAv

HANDOFF = "/handoff"


def adopt_command(ws):
    return (f"python3 {HELPER} adopt --ws {shlex.quote(ws)} --app /app --patch {HANDOFF}/a.patch "
            f"--records {HANDOFF}/records.json --out {LOG}")


class HandoffBAv(ClaudeCodeAv):
    START_ARGS: ClassVar[str] = " --base-rev HEAD"  # /app holds A's uncommitted work on top of HEAD

    @override
    async def _prepare_workspace(self, environment: BaseEnvironment, ws: str) -> None:
        probe = await environment.exec(command=f"test -f {HANDOFF}/records.json && test -f {HANDOFF}/a.patch")
        if probe.return_code != 0:
            raise RuntimeError(f"HandoffBAv runs only the records channel: no {HANDOFF}/records.json or a.patch")
        await self.exec_as_agent(environment, timeout_sec=300, command=adopt_command(ws))
        await self.exec_as_root(environment, command=f"rm -rf {HANDOFF}")
