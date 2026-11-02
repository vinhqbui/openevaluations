"""Statistics for oe/1 sessions: Wilson intervals, bootstrap CIs, paired arm deltas, change flags.

Rules shared with scholion-bench: medians with a percentile bootstrap, paired deltas resampled
within each task, and no significance claim below 30 valid sessions per cell.
"""

import math
import random
import statistics as st
from collections import OrderedDict

NO_CLAIM_BELOW = 30
LOW_N = 12


def median(v):
    return st.median(v) if v else None


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_ci(values, stat=median, n=2000, seed=1):
    v = [x for x in values if x is not None]
    if not v:
        return (None, None)
    rng = random.Random(seed)
    boots = sorted(stat([rng.choice(v) for _ in v]) for _ in range(n))
    return (boots[int(n * 0.025) - 1], boots[int(n * 0.975) - 1])


def valid(sessions):
    """Sessions that count: ok status (invalid, error and skipped ones never do)."""
    return [s for s in sessions if s.get("status") == "ok"]


def summary(sessions, seed=1):
    ok = valid(sessions)
    n, k = len(ok), sum(1 for s in ok if s.get("accepted"))
    costs = [s["cost_usd"] for s in ok if s.get("cost_usd") is not None]
    lo, hi = wilson(k, n)

    def med(key):
        return median([s[key] for s in ok if s.get(key) is not None])

    cpa = sum(costs) / k if k and len(costs) == n else None
    cpa_ci = (None, None)
    if cpa is not None:
        # resample sessions; the statistic is spend over accepted
        def stat(sample):
            acc = sum(1 for s in sample if s["accepted"])
            return sum(s["cost_usd"] for s in sample) / acc if acc else float("inf")

        rng = random.Random(seed)
        boots = sorted(stat([rng.choice(ok) for _ in ok]) for _ in range(2000))
        cpa_ci = (boots[49], boots[1949])
        cpa_ci = tuple(None if math.isinf(x) else x for x in cpa_ci)
    return {
        "n": n,
        "accepted": k,
        "rate": k / n if n else None,
        "wilson": [lo, hi],
        "cost_per_accepted": cpa,
        "cost_per_accepted_ci": list(cpa_ci),
        "median_tokens_billed": med("tokens_billed"),
        "median_turns": med("turns"),
        "median_llm_calls": med("llm_calls"),
        "median_tool_calls": med("tool_calls"),
        "median_wall_secs": med("wall_secs"),
        "dead_ends": sum(s.get("repeated_dead_ends") or 0 for s in ok),
        "skipped": sum(1 for s in sessions if s.get("status") == "skipped"),
        "invalid": sum(1 for s in sessions if s.get("status") in ("invalid", "error")),
        "cost_estimated": any(s.get("cost_source") in ("estimated", "capped") for s in ok),
    }


METRICS = OrderedDict(
    cost=lambda s: s.get("cost_usd"),
    tokens=lambda s: s.get("tokens_billed"),
    turns=lambda s: s.get("turns"),
    wall=lambda s: s.get("wall_secs"),
    tok_first_edit=lambda s: s.get("tokens_to_first_edit"),
)


def _by_task(sessions):
    by = OrderedDict()
    for s in sessions:
        if s.get("status") != "ok" or s.get("truncated"):
            continue
        by.setdefault(s["task"], []).append(s)
    return by


def _rel(base, arm, f, rng=None):
    out = []
    for t in base:
        if t not in arm:
            continue
        b, a = base[t], arm[t]
        if rng:
            b = [rng.choice(b) for _ in b]
            a = [rng.choice(a) for _ in a]
        av = [v for v in map(f, a) if v is not None]
        bv = [v for v in map(f, b) if v is not None]
        if av and bv and st.mean(bv):
            out.append(st.mean(av) / st.mean(bv) - 1)
    return st.mean(out) if out else None


def paired_report(base_sessions, arm_sessions, metrics=METRICS, seed=1):
    """{metric: (point, lo, hi)}: mean over tasks of arm/base - 1, task-stratified bootstrap.

    A port of scholion's bench/results/2026-10-27-haiku/paired.py: the same resampling order
    and the same seed reproduce its printed numbers.
    """
    base, arm = _by_task(base_sessions), _by_task(arm_sessions)
    rng = random.Random(seed)
    out = OrderedDict()
    for name, f in metrics.items():
        point = _rel(base, arm, f)
        if point is None:
            out[name] = (None, None, None)
            continue
        boots = sorted(x for x in (_rel(base, arm, f, rng) for _ in range(2000)) if x is not None)
        out[name] = (point, boots[50], boots[1949]) if len(boots) == 2000 else (point, None, None)
    return out


def detect_change(current, history, window=4, drop=0.15, tool_factor=1.5):
    """Flags for `current` against up to `window` earlier runs of the same series.

    current/history items are {"run": {...}, "sessions": [...]}, history oldest first.
    """
    cur = valid(current["sessions"])
    n = len(cur)
    if n < LOW_N:
        return ["low_n"]
    base_runs = history[-window:]
    if not base_runs:
        return []
    base = [s for h in base_runs for s in valid(h["sessions"])]
    if not base:
        return []
    k = sum(1 for s in cur if s.get("accepted"))
    base_rate = sum(1 for s in base if s.get("accepted")) / len(base)
    flags = []
    if wilson(k, n)[1] < base_rate - drop:
        flags.append("degraded")
    tc_cur = median([s["tool_calls"] for s in cur if s.get("tool_calls") is not None])
    tc_base = median([s["tool_calls"] for s in base if s.get("tool_calls") is not None])
    if tc_cur is not None and tc_base and tc_cur > tool_factor * tc_base:
        flags.append("tool_calls_up")
    prev_flags = set(base_runs[-1]["run"].get("flags") or [])
    if not flags and prev_flags & {"degraded", "tool_calls_up"}:
        flags.append("recovered")
    return flags
