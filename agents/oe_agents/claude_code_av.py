"""Claude Code on the Scholion framework, as a Harbor agent: the `av` arm of the tracker.

    PYTHONPATH=agents harbor run -a oe_agents.claude_code_av:ClaudeCodeAv -m anthropic/<model> ...

Per trial, after Harbor's own Claude Code install:
1. install: the pinned Scholion release (av, scholion, scholion-daemon), downloaded once on the
   host, sha256-checked and uploaded, so trials neither hit GitHub nor drift.
2. setup: `av up` (the daemon with its bundled Postgres, as the non-root agent user, which
   Postgres requires) and `av repo add app /app`.
3. run: start the task over HTTP (av_container.py start), check the jj workspace holds /app byte
   for byte, put the workspace at /app, then run Claude Code exactly as the cold arm does, plus
   the av hooks in its --settings. Afterwards: checkpoint, export records, keep the daemon log.
4. populate_context_post_run: hook counts and validity (av_settings.evaluate) into metadata;
   `oe import-harbor` turns `oe_invalid` into status "invalid".

The agent name stays "claude-code": the tracker tells the legs apart by arm ("cold" vs "av").
"""

import json
import shlex
from pathlib import Path
from typing import ClassVar, override

from harbor.agents.installed.claude_code import ClaudeCode, ClaudeCodeOptions
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from pydantic import Field

from oe_agents.av_settings import (
    AV_ENV, AV_RELEASE, LOG, TARBALL, evaluate, glibc_ok, hook_settings, merge_settings, release_tarball,
)

HELPER = "/installed-agent/oe_av.py"
PATH = 'export PATH="$HOME/.local/bin:$PATH"'


class ClaudeCodeAvOptions(ClaudeCodeOptions):
    av_version: str = Field(default=AV_RELEASE, description="Scholion release; only the pinned one is accepted.")
    av_hook_budget: int = Field(default=800, description="Token budget of the SessionStart pack.")
    av_jit_hooks: bool = Field(default=True, description="Also the PreToolUse and Stop hooks.")


class ClaudeCodeAv(ClaudeCode):
    options_model = ClaudeCodeAvOptions
    options: ClaudeCodeAvOptions
    # Claude Code's own install takes 3-6 minutes (apt nodejs); av adds the upload and `av up`.
    DEFAULT_SETUP_TIMEOUT_SEC: ClassVar[float] = 900.0
    START_ARGS: ClassVar[str] = ""  # extra `oe_av.py start` flags (the handoff successor's --base-rev)

    def __init__(self, logs_dir: Path, *args, **kwargs):
        user = kwargs.pop("config", None)
        if isinstance(user, (str, Path)):
            user = json.loads(Path(user).read_text(encoding="utf-8"))
        hooks = hook_settings(int(kwargs.get("av_hook_budget", 800)), _bool(kwargs.get("av_jit_hooks", True)))
        kwargs["extra_env"] = {**AV_ENV, **(kwargs.get("extra_env") or {})}
        super().__init__(logs_dir, *args, config=merge_settings(user, hooks), **kwargs)
        if self.options.av_version != AV_RELEASE:
            raise ValueError(f"av_version {self.options.av_version!r}: only {AV_RELEASE} is pinned (sha256)")
        self._av_version = None

    @override
    async def install(self, environment: BaseEnvironment) -> None:
        await super().install(environment)
        probe = await self.exec_as_agent(environment, command="id -u; ldd --version 2>&1 | sed -n 1p")
        uid, _, ldd = (probe.stdout or "").strip().partition("\n")
        if uid.strip() == "0":
            raise RuntimeError("the av arm needs a non-root agent user ([agent] user in task.toml): Postgres refuses root")
        if not glibc_ok(ldd):
            raise RuntimeError(f"the Scholion release needs glibc >= 2.39; the image has: {ldd!r}")
        await environment.upload_file(release_tarball(), "/tmp/scholion.tar.gz")
        await environment.upload_file(Path(__file__).with_name("av_container.py"), HELPER)
        await self.exec_as_root(environment, command=f"chmod a+r /tmp/scholion.tar.gz {HELPER}")
        out = await self.exec_as_agent(environment, command=(
            "set -euo pipefail; mkdir -p ~/.local/bin /tmp/sch && tar -xzf /tmp/scholion.tar.gz -C /tmp/sch && "
            f"install -m 0755 /tmp/sch/{TARBALL}/av /tmp/sch/{TARBALL}/scholion /tmp/sch/{TARBALL}/scholion-daemon "
            "~/.local/bin/ && rm -rf /tmp/sch && ~/.local/bin/av --version"))
        self._av_version = (out.stdout or "").strip().splitlines()[-1] if out.stdout else None

    @override
    async def setup(self, environment: BaseEnvironment) -> None:
        await super().setup(environment)
        try:
            await self.exec_as_agent(environment, timeout_sec=300, command=(
                f"{PATH}; mkdir -p {LOG} && : > {LOG}/hook-count && : > {LOG}/hooks.err && "
                f"av --version > {LOG}/av-version.txt && T0=$(date +%s) && "
                f"av up && av repo add app /app && echo $(( $(date +%s) - T0 )) > {LOG}/up-secs"))
        except Exception:
            await self._quiet(environment, f"cp ~/.scholion/daemon.log {LOG}/ 2>/dev/null; true")
            raise

    @override
    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        health = await environment.exec(command="curl -fsS http://127.0.0.1:7420/healthz")
        if health.return_code != 0:  # the daemon should outlive the setup exec; restart if it did not
            await self.exec_as_agent(environment, timeout_sec=240,
                                     command=f"{PATH}; av up && echo 1 > {LOG}/daemon-restarted")
        title = (instruction.strip().splitlines() or ["task"])[0][:80]
        started = await self.exec_as_agent(environment, timeout_sec=180, env={"OE_AV_GOAL": instruction}, command=(
            f"python3 {HELPER} start --title {shlex.quote(title)} --goal-env OE_AV_GOAL "
            f"--base /app --repo app --out {LOG}{self.START_ARGS}"))
        ws = (started.stdout or "").strip().splitlines()[-1]
        if not ws.startswith("/"):
            raise RuntimeError(f"av task start printed no workspace path: {started.stdout!r}")
        await self._prepare_workspace(environment, ws)
        # The agent and the verifier both work in /app; make it the task's jj workspace.
        await self.exec_as_root(environment, command=f"mv /app /app.base && ln -s {shlex.quote(ws)} /app")
        try:
            await self._run_claude(instruction, environment, context)
        finally:
            await self._quiet(environment, f"python3 {HELPER} finish --out {LOG}; "
                              f"cp ~/.scholion/daemon.log {LOG}/ 2>/dev/null; true", timeout_sec=120)

    async def _prepare_workspace(self, environment: BaseEnvironment, ws: str) -> None:
        """Between the task start and the swap of /app: nothing here (the handoff successor fills it)."""

    async def _run_claude(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        """Claude Code exactly as the cold arm runs it (the handoff predecessor adds a wrap-up)."""
        await ClaudeCode.run(self, instruction, environment, context)

    async def _quiet(self, environment, command, timeout_sec=60):
        """Best effort, as the agent user: never raises (it runs in finally/except paths)."""
        try:
            await self.exec_as_agent(environment, command=command, timeout_sec=timeout_sec)
        except Exception as e:
            self.logger.debug(f"av: {command[:60]}... failed: {e}")

    @override
    def populate_context_post_run(self, context: AgentContext) -> None:
        super().populate_context_post_run(context)
        meta = evaluate(self.logs_dir / "scholion")
        meta["av_version"] = meta.get("av_version") or self._av_version
        context.metadata = {**(context.metadata or {}), **meta}


def _bool(v):
    return v if isinstance(v, bool) else str(v).strip().lower() not in ("0", "false", "no", "off", "")
