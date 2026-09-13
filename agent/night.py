"""Night Runner — the all-night autonomous loop.

No human in the loop. Each night it:
  1. SCOUTS the top-10 best-selling / high-commission products.
  2. Runs the FACTORY across those products, cycling bandit-chosen viral
     styles, generating + enhancing HD promo videos with affiliate landing
     pages, over and over until the night's time budget is spent.
  3. Periodically SELF-TUNES (optimizer.evolve) so it learns and grows.
  4. Records accounting and halts only if insolvent.

Deployment: GitHub Actions caps a job at ~6h, so in CI this produces a solid
nightly BATCH (NIGHT_MAX_ASSETS). On a 24x7 machine / VPS, set NIGHT_HOURS to
run the true all-night grind. Both paths share this same code.
"""
import os
import time
from datetime import datetime, timezone

from . import bus, config, gitsync, ledger, optimize, reflect, scout, selfheal
from .brain import Brain
from .factory import make_asset


def _backend_label(brain):
    if brain.omniroute and brain._omni_reachable():
        return f"omniroute:{config.OMNIROUTE_MODEL}" + (
            " (+gemini fallback)" if brain.gemini else "")
    if brain.gemini:
        return f"gemini:{config.GEMINI_MODEL}"
    return "offline"


def run_night():
    hours = float(os.environ.get("NIGHT_HOURS", "0"))          # 0 = batch mode
    max_assets = int(os.environ.get("NIGHT_MAX_ASSETS", "10"))  # per run cap
    make_video = os.environ.get("MAKE_VIDEO", "1") == "1"
    top_n = int(os.environ.get("SCOUT_TOP_N", "10"))

    deadline = time.time() + hours * 3600 if hours > 0 else None
    print(f"=== NIGHT RUN {datetime.now(timezone.utc).isoformat()} ===")
    print(f"Balance: ${ledger.balance():.4f} | solvent: {ledger.is_solvent()}")
    if not ledger.is_solvent():
        print("!! Insolvent — halting to avoid running up costs.")
        return 1

    brain = Brain()
    print(f"Brain backend: {_backend_label(brain)}")

    # Self-heal: take vitals and route around any broken parts BEFORE working.
    health = selfheal.preflight(brain)
    print(f"[selfheal] healthy={health['healthy']} "
          f"actions={health.get('actions') or 'none'}")

    if not make_video:
        # let the factory skip the heavy renderer
        os.environ["FACTORY_NO_VIDEO"] = "1"

    # 1) scout tonight's money list — via the research swarm if enabled
    swarm_n = int(os.environ.get("SWARM_WORKERS", str(config.SWARM_WORKERS)))
    if swarm_n > 0 and not selfheal.circuit_open("swarm"):
        from . import swarm
        try:
            products = swarm.research_swarm(brain, n_workers=swarm_n,
                                            top_n=top_n)
        except Exception as e:
            selfheal.record_incident("swarm", e)
            products = []
        if not products:  # swarm came back empty -> safe fallback
            products = scout.run(brain, top_n=top_n)
    else:
        products = scout.run(brain, top_n=top_n)
    print(f"[scout] {len(products)} products. Top opportunities:")
    for p in products[:5]:
        print(f"   - {p['product']}  (heat {p['heat']}, "
              f"comm {int(p['commission']*100)}%, opp {p['opportunity']})")

    # 2) grind: cycle products x styles, self-tuning as we go
    produced = 0
    idx = 0
    strat = optimize.load_strategy()
    while produced < max_assets:
        if deadline and time.time() > deadline:
            print("[night] time budget reached.")
            break
        product = products[idx % len(products)]
        style, _ = optimize.pick_style(strat)
        try:
            res = make_asset(brain, product, style=style)
            produced += 1
            print(f"[factory] {produced}/{max_assets} "
                  f"{'+video' if res.get('video') else 'post'} "
                  f"[{style}] {res['product']}")
        except Exception as e:
            selfheal.record_incident("factory", e)
            print(f"[factory] error on {product.get('product')}: {str(e)[:120]}")
        idx += 1
        # self-tune every 3 assets so it keeps learning through the night
        if produced and produced % 3 == 0:
            strat = optimize.evolve()
            print(f"[optimize] gen {strat['generation']} "
                  f"best_style={bus.get_intel('strategy', {}).get('best')}")

    # 3) final nightly self-fine-tune, then reflect into durable lessons
    strat = optimize.evolve()
    lessons = reflect.reflect(brain)
    print(f"[reflect] gen {lessons['generation']} | "
          f"lesson: {lessons['guidance']}")

    # 4) accounting
    ledger.record("cost", config.COST_PER_RUN, note=f"night: {produced} assets")

    print(f"[night] produced {produced} assets; "
          f"strategy generation {strat['generation']}")
    print("[comms] recent bus traffic:")
    for m in bus.recent(6):
        print(f"   {m['sender']} -> {m['topic']}")
    print("Ledger:", ledger.summary())
    # 5) publish from non-CI hosts (VM/container) when AUTO_PUSH=1
    gitsync.push_if_enabled(note=f"{produced} assets, gen {strat['generation']}")
    print("=== NIGHT RUN COMPLETE ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_night())
