"""OpenAI's Codex CLI on DeepSeek, as a Harbor agent: the `codex` leg of the tracker.

    PYTHONPATH=agents harbor run -a oe_agents.codex_deepseek:CodexDeepSeek -m deepseek/deepseek-flash ...

Harbor's own Codex agent installs the CLI (`npm install -g @openai/codex@<version>`), runs
`codex exec --json` and turns the rollout into ATIF. This subclass only hands it a native
config with the DeepSeek provider (codex_settings.provider_config); Harbor merges that with its
runtime inputs and uploads it as `$CODEX_HOME/config.toml`. The agent name stays "codex".
"""

import tomllib
from pathlib import Path

from harbor.agents.installed.codex import Codex

from oe_agents.codex_settings import provider_config


class CodexDeepSeek(Codex):
    def __init__(self, logs_dir: Path, *args, **kwargs):
        user = kwargs.pop("config", None)
        if isinstance(user, (str, Path)):
            user = tomllib.loads(Path(user).read_text(encoding="utf-8"))
        super().__init__(logs_dir, *args, config=provider_config(user), **kwargs)
