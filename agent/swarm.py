"""Research Swarm — many logical research agents, one legit environment.

This is the honest, ToS-safe way to "run 100 research agents": instead of
spawning 100 hosts and creating 100 accounts (which gets every linked account
banned and duplicate-content-penalised), we dispatch up to N *logical* research
workers concurrently INSIDE the one environment you already own. Each worker is
a distinct research "agent" with its own mission (a category x angle combo),
they all share the message bus, and their findings are merged, de-duplicated
and scored by the same commission-aware model the scout uses.

Result: the breadth of a big research team, with a single account footprint,
no self-replication, and no free-tier farming.
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import bus, config, scout

NAME = "research-swarm"

# Money-friendly categories (favouring higher Amazon.in commission bands).
_CATEGORIES = [
    "face & skin care", "hair care", "men's grooming", "makeup & beauty",
    "kitchen & cookware", "home organisation", "home decor & lighting",
    "health & nutrition", "fitness & gym gear", "yoga & wellness",
    "women's fashion", "men's fashion", "watches & accessories",
    "bags & luggage", "baby & mother care", "pet supplies",
    "stationery & office", "car accessories", "gardening & outdoor",
    "smart home accessories",
]

# Research angles that surface different winners for the same category.
_ANGLES = [
    "current best-sellers with lots of reviews",
    "fast-trending products people are buying this month",
    "problem-solving products with strong repeat demand",
    "great gifting picks under a modest budget",
    "premium picks with high order value",
    "viral-on-social products getting buzz",
    "seasonal must-haves right now",
    "underrated hidden-gem products",
]


def _missions(n):
    """Build n distinct research missions, spread across categories first.

    Round-robin over categories (category-major) so even a small swarm covers
    many categories before repeating, and every category is represented.
    """
    C, A = len(_CATEGORIES), len(_ANGLES)
    missions = []
    k = 0
    while len(missions) < n:
        cat = _CATEGORIES[k % C]
        angle = _ANGLES[(k // C) % A]
        missions.append({"agent": f"researcher-{len(missions)+1:03d}",
                         "category": cat, "angle": angle})
        k += 1
    return missions


def _worker(brain, mission):
    """One logical research agent: return a few specific product candidates."""
    prompt = f"""You are {mission['agent']}, an Amazon India affiliate product
researcher. Focus ONLY on: {mission['category']} — {mission['angle']}.
List 4 SPECIFIC products (real product types, not vague categories) that fit.
Return STRICT JSON list, each: {{"product": "...",
"search_query": "amazon search phrase", "category": "{mission['category']}",
"heat": 1-10 demand score}}."""
    try:
        data = brain.think(prompt, as_json=True)
    except Exception as e:  # noqa
        return mission, [], str(e)[:100]
    items = data if isinstance(data, list) else (
        data.get("products") or data.get("items") if isinstance(data, dict)
        else [])
    return mission, (items or []), None


def research_swarm(brain, n_workers=None, concurrency=None, top_n=10):
    """Dispatch the swarm, merge findings, return the ranked money list."""
    n = n_workers or config.SWARM_WORKERS or 100
    conc = max(1, concurrency or config.SWARM_CONCURRENCY)
    missions = _missions(n)

    bus.post(NAME, "swarm_start",
             {"workers": n, "concurrency": conc,
              "categories": len(set(m["category"] for m in missions))})
    print(f"[swarm] dispatching {n} research agents "
          f"(<= {conc} concurrent) across {len(_CATEGORIES)} categories...")

    found, ok, failed = [], 0, 0
    with ThreadPoolExecutor(max_workers=conc) as pool:
        futs = {pool.submit(_worker, brain, m): m for m in missions}
        for fut in as_completed(futs):
            try:
                mission, items, err = fut.result(
                    timeout=config.SWARM_WORKER_TIMEOUT)
            except Exception:
                failed += 1
                continue
            if err or not items:
                failed += 1
                continue
            ok += 1
            for it in items:
                if isinstance(it, dict) and it.get("product"):
                    it.setdefault("category", mission["category"])
                    found.append(it)

    print(f"[swarm] {ok} agents reported, {failed} empty/failed, "
          f"{len(found)} raw candidates.")

    ranked = _merge_and_rank(found, top_n)
    payload = {"source": "swarm", "workers": n, "candidates": len(found),
               "products": ranked}
    (config.STATE_DIR / "swarm_report.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False))
    bus.set_intel("daily_products", ranked)
    bus.post(NAME, "swarm_done",
             {"reported": ok, "candidates": len(found),
              "selected": len(ranked),
              "top": ranked[0]["product"] if ranked else None})
    return ranked


def _merge_and_rank(found, top_n, per_cat=3):
    """De-duplicate, score by opportunity, keep top_n with category variety.

    Caps products per category (default 3) so the night's content isn't all
    the same niche, while still preferring the highest-opportunity items.
    """
    best = {}
    for it in found:
        name = str(it.get("product", "")).strip()
        if not name:
            continue
        key = name.lower()
        cat = (it.get("category") or name).strip()
        heat = int(it["heat"]) if str(it.get("heat", "")).strip().isdigit() else 6
        heat = max(1, min(heat, 10))
        rate = scout.commission_rate(f"{name} {cat}")
        cand = {
            "product": name,
            "search_query": it.get("search_query") or name,
            "category": cat,
            "heat": heat,
            "commission": rate,
            "opportunity": round(heat * rate * 100, 1),
        }
        if key not in best or cand["opportunity"] > best[key]["opportunity"]:
            best[key] = cand

    ordered = sorted(best.values(), key=lambda x: x["opportunity"], reverse=True)
    # first pass: enforce per-category diversity
    picked, counts = [], {}
    for c in ordered:
        cat = c["category"].lower()
        if counts.get(cat, 0) < per_cat:
            picked.append(c)
            counts[cat] = counts.get(cat, 0) + 1
        if len(picked) >= top_n:
            break
    # second pass: backfill with the best remaining if still short
    if len(picked) < top_n:
        chosen = {p["product"].lower() for p in picked}
        for c in ordered:
            if c["product"].lower() not in chosen:
                picked.append(c)
                if len(picked) >= top_n:
                    break
    return picked[:top_n]
