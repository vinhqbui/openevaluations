"""Sums what a jobs directory spent, so a scheduled run can stop before its cap."""

import json
import tomllib
from pathlib import Path

PRICES = Path(__file__).with_name("prices.toml")
# Agents whose Harbor adapter never reports a cost (Codex: only through litellm, which Harbor
# does not install); their tokens are priced from prices.toml and the row says "estimated".
NO_COST_AGENTS = {"codex"}


def _prices():
    return tomllib.loads(PRICES.read_text(encoding="utf-8")).get("models", {})


def estimate(model, n_in, n_cache, n_out):
    """USD from prices.toml ($ per million tokens), or None for an unknown model."""
    p = _prices().get((model or "").split("/")[-1])
    if not p or n_in is None or n_out is None:
        return None
    cache = n_cache or 0
    return ((n_in - cache) * p["input"] + cache * p.get("cache_read", p["input"]) + n_out * p["output"]) / 1e6


def trial_cost(r):
    """(cost_usd or None, cost_source) of one Harbor trial result.

    Claude Code prices a non-Claude model (DeepSeek through its Anthropic-compatible API) at a
    Claude list-price fallback (costBasis "unknown"), about 20x too high: re-price from prices.toml.
    Codex reports none at all (NO_COST_AGENTS): price its tokens the same way.
    """
    info = r.get("agent_info") or {}
    model = ((info.get("model_info") or {}).get("name") or "").split("/")[-1]
    ar = r.get("agent_result") or {}
    meta = ar.get("metadata") or {}
    if info.get("name") == "claude-code" and model and not model.startswith("claude"):
        cost = estimate(model, ar.get("n_input_tokens"), ar.get("n_cache_tokens"), ar.get("n_output_tokens"))
        return cost, "unavailable" if cost is None else "estimated"
    cost = ar.get("cost_usd")
    if cost is None and info.get("name") in NO_COST_AGENTS:
        cost = estimate(model, ar.get("n_input_tokens"), ar.get("n_cache_tokens"), ar.get("n_output_tokens"))
        return cost, "unavailable" if cost is None else "estimated"
    if cost is None:
        return None, "unavailable"
    return cost, "estimated" if meta.get("cost_source") == "litellm_estimate" else "measured"


def spent(jobs_dir):
    """(total_usd, trials_without_any_price) over every trial result.json under jobs_dir."""
    total, unpriced = 0.0, 0
    for res in Path(jobs_dir).rglob("result.json"):
        try:
            r = json.loads(res.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if "trial_name" not in r:
            continue
        ar = r.get("agent_result") or {}
        cost, _ = trial_cost(r)
        if cost is None:
            model = ((r.get("agent_info") or {}).get("model_info") or {}).get("name")
            cost = estimate(model, ar.get("n_input_tokens"), ar.get("n_cache_tokens"), ar.get("n_output_tokens"))
        if cost is None:
            unpriced += 1
        else:
            total += cost
    return total, unpriced
