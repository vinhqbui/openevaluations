"""Codex CLI's custom model provider for the tracker: DeepSeek through its Responses API.

Codex reads `model_provider` and `[model_providers.<id>]` from `$CODEX_HOME/config.toml`
(`base_url`, `env_key`, `wire_api`). Since Codex removed `wire_api = "chat"`, a provider must
speak the OpenAI Responses API; DeepSeek serves it at `https://api.deepseek.com/v1/responses`
(checked 2026-11-04). The key stays in the environment variable `env_key` names: locally
`DEEPSEEK_API_KEY`, in CI the `LLM_API_KEY` secret exported under that name by the workflow step.

Pure and importable without Harbor, so CI (which installs no Harbor) tests it.
"""

from copy import deepcopy

PROVIDER = "deepseek"
BASE_URL = "https://api.deepseek.com/v1"
ENV_KEY = "DEEPSEEK_API_KEY"


def provider_config(user=None, *, provider=PROVIDER, base_url=BASE_URL, env_key=ENV_KEY):
    """The Codex config as a dict: `user`'s settings plus the provider, selected as the default."""
    cfg = deepcopy(user) if user else {}
    cfg["model_provider"] = provider
    providers = cfg.setdefault("model_providers", {})
    providers[provider] = {"name": "DeepSeek", "base_url": base_url, "env_key": env_key, "wire_api": "responses"}
    return cfg
