"""The Codex arm: OpenAI's Codex CLI on DeepSeek through a custom model provider."""

import tomllib

import pytest

from oe_agents.codex_settings import BASE_URL, ENV_KEY, PROVIDER, provider_config


def test_provider_config_points_codex_at_deepseeks_responses_api():
    c = provider_config()
    assert c["model_provider"] == PROVIDER == "deepseek"
    p = c["model_providers"]["deepseek"]
    assert p["base_url"] == BASE_URL == "https://api.deepseek.com/v1"
    # Codex appends /responses; it accepts no other wire API since `chat` was removed
    assert p["wire_api"] == "responses"
    # the key is read from the environment at start, never written into the file
    assert p["env_key"] == ENV_KEY == "DEEPSEEK_API_KEY"
    assert not any("sk-" in str(v) for v in p.values())


def test_provider_config_keeps_the_users_settings_and_does_not_mutate_them():
    user = {"model_reasoning_effort": "low", "model_providers": {"other": {"base_url": "http://x"}}}
    c = provider_config(user)
    assert c["model_reasoning_effort"] == "low"
    assert c["model_providers"]["other"] == {"base_url": "http://x"}
    assert c["model_providers"]["deepseek"]["env_key"] == "DEEPSEEK_API_KEY"
    assert user == {"model_reasoning_effort": "low", "model_providers": {"other": {"base_url": "http://x"}}}


# --- the Harbor subclass (only where Harbor is installed: `uv sync --extra run`) ---------------

def test_harbor_agent_renders_the_provider_into_codex_config_toml(tmp_path, monkeypatch):
    pytest.importorskip("harbor")
    import toml

    from oe_agents.codex_deepseek import CodexDeepSeek

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    for v in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL", "CODEX_AUTH_JSON_PATH", "CODEX_FORCE_AUTH_JSON"):
        monkeypatch.delenv(v, raising=False)
    a = CodexDeepSeek(logs_dir=tmp_path, model_name="deepseek/deepseek-flash", version="0.166.0")
    assert CodexDeepSeek.name() == "codex"  # rows say "codex"; the provider is in the model
    assert a._resolved_model_name() == "deepseek-flash"
    access = a.model_connection
    assert access.api_key_destination_name == "DEEPSEEK_API_KEY"
    assert access.env.get("DEEPSEEK_API_KEY") == "test-key"
    # what Harbor uploads to $CODEX_HOME/config.toml, after its own runtime merge
    rendered = toml.dumps(a._build_effective_config(a._resolved_base_url()))
    assert "test-key" not in rendered
    cfg = tomllib.loads(rendered)
    assert cfg["model_provider"] == "deepseek"
    assert cfg["model_providers"]["deepseek"] == {
        "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_API_KEY", "wire_api": "responses",
    }
    assert "openai_base_url" not in cfg
