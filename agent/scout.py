"""Product Scout Agent — the nightly money-radar.

Every night this builds a ranked list of ~10 products that are BOTH
best-selling AND pay a worthwhile affiliate commission, then hands them to the
content/video factory.

Why a commission model matters: on Amazon India, phones/laptops/TVs are huge
sellers but pay only ~1-2%, while accessories, home, kitchen, beauty and
grooming pay ~5-9%. Chasing raw popularity alone earns almost nothing — so we
score every candidate by  opportunity = demand_heat * commission_rate  and let
that drive what the factory produces.
"""
import json
from datetime import datetime, timezone

from . import bus, config

NAME = "scout-agent"

_PRODUCTS_PATH = config.STATE_DIR / "daily_products.json"

# Approximate Amazon.in Associates commission rates by category keyword.
# (Fixed advertising fees change; these are conservative planning figures.)
_COMMISSION = {
    "beauty": 0.09, "grooming": 0.09, "skincare": 0.09, "skin care": 0.09,
    "makeup": 0.09, "perfume": 0.09, "fragrance": 0.09,
    "apparel": 0.07, "clothing": 0.07, "fashion": 0.07, "shoes": 0.07,
    "watch": 0.07, "jewel": 0.07, "bag": 0.07, "luggage": 0.07,
    "home": 0.08, "kitchen": 0.08, "cookware": 0.08, "decor": 0.08,
    "furniture": 0.08, "bedsheet": 0.08, "mattress": 0.06,
    "health": 0.07, "supplement": 0.07, "personal care": 0.07,
    "grocery": 0.05, "pet": 0.06, "toy": 0.06, "book": 0.04,
    "sports": 0.06, "fitness": 0.06, "yoga": 0.06, "outdoor": 0.06,
    "accessory": 0.05, "accessories": 0.05, "cable": 0.05, "case": 0.05,
    "charger": 0.05, "mount": 0.05, "stand": 0.05, "keyboard": 0.05,
    "mouse": 0.05, "headphone": 0.04, "earbud": 0.04, "speaker": 0.04,
    "smartwatch": 0.04, "wearable": 0.04, "camera": 0.03, "drone": 0.03,
    "appliance": 0.03, "vacuum": 0.03, "purifier": 0.03, "printer": 0.03,
    "monitor": 0.025, "ssd": 0.025, "storage": 0.025, "router": 0.03,
    "laptop": 0.015, "tablet": 0.015, "tv": 0.02, "television": 0.02,
    "phone": 0.01, "mobile": 0.01, "smartphone": 0.01, "console": 0.01,
}
_DEFAULT_RATE = 0.04

# Curated high-opportunity fallback (specific, buy-now products).
_FALLBACK = [
    {"product": "Vitamin C face serum", "search_query": "vitamin c face serum",
     "category": "beauty", "heat": 9},
    {"product": "Beard trimmer kit", "search_query": "beard trimmer for men",
     "category": "grooming", "heat": 8},
    {"product": "Air fryer 4L", "search_query": "air fryer 4 litre",
     "category": "kitchen", "heat": 9},
    {"product": "Non-stick cookware set", "search_query": "non stick cookware set",
     "category": "kitchen", "heat": 7},
    {"product": "Yoga mat 6mm", "search_query": "yoga mat 6mm anti slip",
     "category": "fitness", "heat": 7},
    {"product": "Resistance bands set", "search_query": "resistance bands set",
     "category": "fitness", "heat": 7},
    {"product": "Whey protein 1kg", "search_query": "whey protein 1kg",
     "category": "supplement", "heat": 8},
    {"product": "Ceramic hair straightener", "search_query": "hair straightener",
     "category": "beauty", "heat": 8},
    {"product": "Insulated water bottle", "search_query": "insulated steel water bottle",
     "category": "home", "heat": 7},
    {"product": "LED strip lights", "search_query": "led strip lights for room",
     "category": "decor", "heat": 8},
]


def commission_rate(text):
    t = (text or "").lower()
    best = 0.0
    for kw, rate in _COMMISSION.items():
        if kw in t and rate > best:
            best = rate
    return best or _DEFAULT_RATE


def _score(item):
    heat = item.get("heat", 5)
    rate = item.get("commission", _DEFAULT_RATE)
    # opportunity = demand * commission, scaled to a friendly 0-100.
    return round(heat * rate * 100, 1)


def run(brain, top_n=10):
    """Discover tonight's best money-making products. Returns ranked list."""
    query = f"""You are an affiliate profit researcher for Amazon India
({config.AMAZON_DOMAIN}). List {top_n + 6} SPECIFIC products that are selling
extremely well right now AND sit in categories that pay a healthy affiliate
commission (favour beauty, grooming, home, kitchen, health, fitness, fashion
and accessories over phones/laptops/TVs which pay almost nothing).
Return STRICT JSON list, each item:
{{"product": "specific product", "search_query": "amazon search phrase",
  "category": "one word category", "heat": 1-10 demand score}}."""
    data = brain.research(query, as_json=True)

    raw = data if isinstance(data, list) else (
        data.get("products") or data.get("items") if isinstance(data, dict)
        else None)
    source = "live-research"
    if not raw or not isinstance(raw, list):
        raw, source = _FALLBACK, "fallback"

    clean = []
    seen = set()
    for it in raw:
        if not isinstance(it, dict) or not it.get("product"):
            continue
        name = it["product"].strip()
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        cat = (it.get("category") or name).strip()
        heat = int(it["heat"]) if str(it.get("heat", "")).strip().isdigit() else 6
        rate = commission_rate(f"{name} {cat}")
        item = {
            "product": name,
            "search_query": it.get("search_query") or name,
            "category": cat,
            "heat": max(1, min(heat, 10)),
            "commission": rate,
        }
        item["opportunity"] = _score(item)
        clean.append(item)

    if not clean:
        clean = _FALLBACK
        for it in clean:
            it["commission"] = commission_rate(it["category"])
            it["opportunity"] = _score(it)

    clean.sort(key=lambda x: x["opportunity"], reverse=True)
    clean = clean[:top_n]

    payload = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "source": source,
        "products": clean,
    }
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    _PRODUCTS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    bus.set_intel("daily_products", clean)
    bus.post(NAME, "daily_products",
             {"source": source, "count": len(clean),
              "top": clean[0]["product"],
              "top_opportunity": clean[0]["opportunity"]})
    return clean


def load_today():
    if not _PRODUCTS_PATH.exists():
        return []
    try:
        data = json.loads(_PRODUCTS_PATH.read_text())
    except Exception:
        return []
    if data.get("date") != datetime.now(timezone.utc).strftime("%Y-%m-%d"):
        return []
    return data.get("products", [])
