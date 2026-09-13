"""Amazon Associates link injection.

Until the Product Advertising API is unlocked (needs 3 qualifying sales),
we monetize with compliant tagged *search* links. These are valid affiliate
links and earn commission on any resulting purchase.
"""
from urllib.parse import quote_plus

from . import config


def search_link(query):
    """A tagged Amazon search URL for a product category/query."""
    q = quote_plus(query.strip())
    return (
        f"https://{config.AMAZON_DOMAIN}/s?k={q}&tag={config.AFFILIATE_TAG}"
    )


def recommend(brain, title, body):
    """Ask the brain for relevant product categories, return a Markdown block.

    Returns "" if monetization isn't configured so posts stay clean.
    """
    if not config.AFFILIATE_TAG:
        return ""

    prompt = f"""Given this article titled "{title}", list 3-5 SPECIFIC product
categories or search phrases a reader would realistically buy on Amazon after
reading it. Be concrete (e.g. "wifi 7 mesh router", not "networking").
Return strict JSON: {{"picks": [{{"label": "Human friendly name",
"query": "amazon search phrase"}}]}}."""
    data = brain.think(prompt, as_json=True)
    picks = data.get("picks") if isinstance(data, dict) else None
    if not picks:
        return ""

    lines = ["\n\n## 🛒 Recommended gear\n",
             "_Handpicked categories to explore (affiliate links):_\n"]
    for p in picks[:5]:
        label = (p.get("label") or "").strip()
        query = (p.get("query") or label).strip()
        if not label or not query:
            continue
        lines.append(f"- **[{label}]({search_link(query)})**")
    return "\n".join(lines) + "\n"
