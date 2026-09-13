"""Self-Tuning Agent — the part that learns and grows on its own.

The system has to improve without a human. Two things get tuned every night:

  1. HOOK STYLE   — an epsilon-greedy multi-armed bandit over viral hook
                    archetypes. Styles that earn clicks get produced more;
                    weak ones fade. New styles keep getting explored.
  2. CATEGORY BIAS — realized opportunity + click feedback nudges which
                     product categories the scout/factory favour.

Reward = whatever real performance we can observe (YouTube views, on-site
link clicks, affiliate earnings). Until those analytics feeds are wired, the
bandit self-explores so it is already learning the moment real numbers arrive.
All state lives in state/strategy.json + state/performance.json so learning
persists across nights and across machines (it is committed back by CI).
"""
import json
import random
from datetime import datetime, timezone

from . import bus, config

NAME = "optimizer-agent"

_STRATEGY_PATH = config.STATE_DIR / "strategy.json"
_PERF_PATH = config.STATE_DIR / "performance.json"

EPSILON = 0.20  # exploration rate

# Viral hook archetypes the factory can render. Each is a prompt directive.
HOOK_STYLES = {
    "shock_stat": "Open with a surprising number or statistic.",
    "mistake_warning": "Open by warning about a costly mistake buyers make.",
    "before_after": "Frame it as a dramatic before-vs-after transformation.",
    "myth_bust": "Open by busting a common myth people believe.",
    "countdown": "Frame it as a fast top-3 countdown of picks.",
    "question_hook": "Open with a bold, curiosity-gap question.",
    "secret_reveal": "Tease an insider secret most people don't know.",
    "price_shock": "Lead with a 'you won't believe the price' angle.",
}


def _default_strategy():
    return {
        "styles": {k: {"count": 0, "reward": 0.0} for k in HOOK_STYLES},
        "categories": {},          # category -> {count, reward}
        "updated": None,
        "generation": 0,
    }


def load_strategy():
    if _STRATEGY_PATH.exists():
        try:
            s = json.loads(_STRATEGY_PATH.read_text())
            # heal any newly-added styles
            for k in HOOK_STYLES:
                s.setdefault("styles", {}).setdefault(
                    k, {"count": 0, "reward": 0.0})
            return s
        except Exception:
            pass
    return _default_strategy()


def save_strategy(s):
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    s["updated"] = datetime.now(timezone.utc).isoformat()
    _STRATEGY_PATH.write_text(json.dumps(s, indent=2, ensure_ascii=False))


def _avg(arm):
    c = arm.get("count", 0)
    return (arm.get("reward", 0.0) / c) if c else 0.0


def pick_style(strategy=None):
    """Epsilon-greedy choice of a hook style directive."""
    s = strategy or load_strategy()
    styles = s["styles"]
    if random.random() < EPSILON or all(a["count"] == 0 for a in styles.values()):
        name = random.choice(list(styles))
    else:
        name = max(styles, key=lambda k: _avg(styles[k]))
    return name, HOOK_STYLES[name]


def record_result(style, category, reward, strategy=None, save=True):
    """Feed a realized reward back into the bandit."""
    s = strategy or load_strategy()
    arm = s["styles"].setdefault(style, {"count": 0, "reward": 0.0})
    arm["count"] += 1
    arm["reward"] += float(reward)
    if category:
        cat = s["categories"].setdefault(category, {"count": 0, "reward": 0.0})
        cat["count"] += 1
        cat["reward"] += float(reward)
    if save:
        save_strategy(s)
    return s


# --- performance log -------------------------------------------------------
def log_asset(entry):
    """Append a produced-asset record so rewards can be attributed later."""
    data = _load_perf()
    entry["logged"] = datetime.now(timezone.utc).isoformat()
    data.append(entry)
    _PERF_PATH.write_text(json.dumps(data[-500:], indent=2, ensure_ascii=False))


def _load_perf():
    if _PERF_PATH.exists():
        try:
            return json.loads(_PERF_PATH.read_text())
        except Exception:
            return []
    return []


def observe_rewards():
    """Pull whatever real metrics we can and turn them into bandit rewards.

    Looks for state/metrics.json (a feed that a future analytics collector, or
    the user, can drop in) shaped like:
        {"<asset_id>": {"views": N, "clicks": N, "earnings": N}}
    Reward = clicks + 5*earnings + 0.01*views. Assets with no metric yet get a
    tiny optimistic exploration reward so unseen arms keep getting tried.
    """
    metrics = {}
    mpath = config.STATE_DIR / "metrics.json"
    if mpath.exists():
        try:
            metrics = json.loads(mpath.read_text())
        except Exception:
            metrics = {}

    strat = load_strategy()
    perf = _load_perf()
    updated = 0
    for entry in perf:
        if entry.get("scored"):
            continue
        m = metrics.get(entry.get("id"))
        if m:
            reward = (m.get("clicks", 0) + 5 * m.get("earnings", 0.0)
                      + 0.01 * m.get("views", 0))
            entry["scored"] = True
        else:
            # optimistic exploration signal blended with the product's own
            # opportunity score, so learning is grounded in economics.
            reward = 0.3 + 0.02 * entry.get("opportunity", 0)
        record_result(entry.get("style", "question_hook"),
                      entry.get("category"), reward, strategy=strat, save=False)
        updated += 1
    _PERF_PATH.write_text(json.dumps(perf[-500:], indent=2, ensure_ascii=False))
    save_strategy(strat)
    return updated, strat


def evolve():
    """Nightly self-fine-tune: fold in rewards, bump the generation, report."""
    updated, strat = observe_rewards()
    strat["generation"] = strat.get("generation", 0) + 1
    save_strategy(strat)

    ranked = sorted(strat["styles"].items(),
                    key=lambda kv: _avg(kv[1]), reverse=True)
    best = ranked[0][0] if ranked else "n/a"
    bus.set_intel("strategy", {"generation": strat["generation"], "best": best})
    bus.post(NAME, "evolved",
             {"generation": strat["generation"], "best_style": best,
              "assets_scored": updated})
    return strat


def category_weight(category, strategy=None):
    """Multiplier (>=1) the scout can use to favour proven categories."""
    s = strategy or load_strategy()
    arm = s["categories"].get((category or "").strip())
    if not arm or not arm.get("count"):
        return 1.0
    return 1.0 + min(_avg(arm), 2.0)
