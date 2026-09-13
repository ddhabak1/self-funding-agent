"""Research Agent.

Runs continuously to discover what is BEST-SELLING and HIGH-COMMISSION right
now, so the content team targets products that actually earn. Uses live
internet research (Google Search grounding) when quota allows, otherwise a
curated evergreen fallback so the team never stalls.
"""
from . import bus, config

NAME = "research-agent"

# Evergreen high-interest, decent-commission categories on Amazon India.
_FALLBACK = [
    {"category": "Robot vacuum cleaners", "search_query": "robot vacuum cleaner",
     "why": "High ticket, strong demand, good commission", "heat": 8},
    {"category": "Smartwatches", "search_query": "smartwatch",
     "why": "Evergreen best-seller, frequent upgrades", "heat": 9},
    {"category": "True wireless earbuds", "search_query": "wireless earbuds",
     "why": "Constant best-seller, impulse buys", "heat": 9},
    {"category": "Wi-Fi 6/7 routers", "search_query": "wifi 6 router",
     "why": "Upgrade cycle + work-from-home demand", "heat": 7},
    {"category": "Portable SSDs", "search_query": "portable ssd 1tb",
     "why": "Creators/gamers, higher price point", "heat": 7},
    {"category": "Air purifiers", "search_query": "air purifier for home",
     "why": "Seasonal spikes, high ticket", "heat": 8},
    {"category": "Mechanical keyboards", "search_query": "mechanical keyboard",
     "why": "Enthusiast niche, add-ons", "heat": 6},
]


def run(brain):
    """Produce product intel and share it on the bus. Returns the target list."""
    query = f"""Act as an affiliate market researcher for Amazon India
({config.AMAZON_DOMAIN}). Identify 6 product CATEGORIES that are BOTH
currently best-selling AND tend to pay decent affiliate commission.
Prefer trending, high-demand, mid-to-high ticket items.
Return strict JSON list, each item:
{{"category": "...", "search_query": "amazon search phrase",
  "why": "1 line: why it sells + earns", "heat": 1-10 demand score}}."""
    data = brain.research(query, as_json=True)

    targets = data if isinstance(data, list) else data.get("targets") \
        if isinstance(data, dict) else None
    if not targets or not isinstance(targets, list):
        targets = _FALLBACK
        source = "fallback"
    else:
        source = "live-research"

    # normalize + sort by heat
    clean = []
    for t in targets:
        if not isinstance(t, dict) or not t.get("category"):
            continue
        clean.append({
            "category": t.get("category"),
            "search_query": t.get("search_query") or t.get("category"),
            "why": t.get("why", ""),
            "heat": int(t.get("heat", 5)) if str(t.get("heat", "")).isdigit()
            else 5,
        })
    clean.sort(key=lambda x: x["heat"], reverse=True)
    clean = clean[:6] or _FALLBACK

    bus.set_intel("product_targets", clean)
    bus.post(NAME, "product_targets",
             {"source": source, "top": clean[0]["category"],
              "count": len(clean)})
    return clean
