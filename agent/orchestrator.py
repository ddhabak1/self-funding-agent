"""Orchestrator — runs the multi-agent team for one cycle.

Flow (agents communicate via the bus):
  Research Agent  -> best-selling / high-commission product targets
  Trend Agent     -> picks the single most viral, monetizable idea
  Content Agent   -> writes the on-site article + affiliate links
  Publisher       -> SEO-ready page on the site
  (optional) Shorts Agent -> HD vertical video for social
  Ledger          -> records cost; halts if insolvent
"""
import json

from . import bus, config, ledger, research, trends
from .brain import Brain
from .content import create_content
from .publish import publish


def _load_memory():
    if config.MEMORY_PATH.exists():
        return json.loads(config.MEMORY_PATH.read_text())
    return {"recent_titles": []}


def _save_memory(mem):
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    config.MEMORY_PATH.write_text(json.dumps(mem, indent=2))


def run_cycle(make_short=False):
    print("=== Agent team waking up ===")
    print(f"Balance: ${ledger.balance():.4f} | solvent: {ledger.is_solvent()}")
    if not ledger.is_solvent():
        print("!! Below survival threshold — halting to avoid running up costs.")
        return 1

    brain = Brain()
    if brain.omniroute and brain._omni_reachable():
        backend = f"omniroute:{config.OMNIROUTE_MODEL} (+gemini fallback)" \
            if brain.gemini else f"omniroute:{config.OMNIROUTE_MODEL}"
    elif brain.gemini:
        backend = f"gemini:{config.GEMINI_MODEL}"
    else:
        backend = "offline"
    print(f"Brain online: {brain.online} (backend={backend})")
    memory = _load_memory()

    # 1) Research agent finds what sells + earns
    targets = research.run(brain)
    print(f"[research] {len(targets)} targets, top: {targets[0]['category']}")

    # 2) Trend agent picks the viral idea
    idea = trends.run(brain, memory.get("recent_titles", []))
    print(f"[trends] chose: {idea['title']}")

    # 3) Content agent writes + monetizes
    post = create_content(brain, idea)
    path = publish(post)
    print(f"[content] published: {path.name}")

    # 3b) SHARE it on the public internet + refresh discovery feeds
    try:
        from . import distribute
        asset = {"post": path.name, "product": idea.get("title", post["title"]),
                 "category": idea.get("category", ""), "title": post["title"]}
        dist = distribute.distribute(brain, asset, idea.get("title"))
        print(f"[share] -> {dist['auto_posted'] or 'queued'} | {dist['landing_url']}")
        distribute.build_feed_and_sitemap()
    except Exception as e:
        print(f"[share] skipped: {str(e)[:120]}")

    # 4) Optional shorts agent (heavy; off by default in the content loop)
    if make_short:
        try:
            from .shorts import build_short
            mp4 = build_short(path)
            bus.post("shorts-agent", "short_ready", {"file": str(mp4.name)})
            print(f"[shorts] built: {mp4}")
        except Exception as e:
            print(f"[shorts] skipped: {str(e)[:120]}")

    # 5) Accounting
    ledger.record("cost", config.COST_PER_RUN, note=f"cycle: {post['slug']}")
    _ingest_revenue()

    memory["recent_titles"] = (
        memory.get("recent_titles", []) + [post["title"]])[-30:]
    _save_memory(memory)

    print("[comms] recent bus traffic:")
    for m in bus.recent(5):
        print(f"   {m['sender']} -> {m['topic']}")
    print("Ledger:", ledger.summary())
    print("=== Agent team sleeping ===")
    return 0


def _ingest_revenue():
    """Hook for real payouts (affiliate/ads report API or webhook)."""
    return 0.0
