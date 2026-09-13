"""Content Agent.

Writes a viral, SEO-friendly article for the idea chosen by the Trend Agent,
targeting the researched best-selling / high-commission product, and injects
Amazon affiliate links. This is the on-site 'earning' asset.
"""
from . import config
from .affiliate import recommend, search_link


def write_article(brain, idea):
    title = idea.get("title", "Untitled")
    category = idea.get("category", "")
    prompt = f"""Write a genuinely helpful, original ~650-word blog post titled
"{title}" about {category}. Use clear Markdown with H2 sections. Be practical
and specific: what to look for, key features, common mistakes, and who each
option suits. Where natural, refer to product types/tiers (budget, mid-range,
premium) WITHOUT inventing fake brands, prices, or stats. End with a short
call-to-action. Return only the Markdown body."""
    body = brain.think(prompt)
    if body.startswith("[offline]") or not body.strip():
        body = _fallback_body(title, category)
    return body


def create_content(brain, idea):
    body = write_article(brain, idea)
    # Product-directed affiliate block (uses the researched search query).
    body += _primary_cta(idea)
    body += recommend(brain, idea.get("title", "Untitled"), body)
    return {
        "title": idea.get("title", "Untitled"),
        "slug": idea.get("slug") or "post",
        "tags": idea.get("tags", []),
        "body": body,
    }


def _primary_cta(idea):
    if not config.AFFILIATE_TAG:
        return ""
    q = idea.get("search_query") or idea.get("category") or "tech deals"
    cat = idea.get("category", "these picks")
    return (f"\n\n## Where to buy\n\nBrowse current best-sellers and deals for "
            f"**[{cat}]({search_link(q)})** on Amazon.\n")


def _fallback_body(title, category):
    return (
        f"## {title}\n\n"
        f"Choosing the right {category} comes down to a few key factors: "
        "build quality, core features, battery or performance, and value for "
        "money.\n\n"
        "## What to look for\n\n"
        "- Match the spec to how you'll actually use it.\n"
        "- Prioritise reliability and after-sales support.\n"
        "- Compare a budget, mid-range, and premium option before deciding.\n\n"
        "## Common mistakes\n\n"
        "Buyers often overspend on features they never use, or underspend and "
        "upgrade again within a year. Aim for the sweet spot.\n\n"
        "## Bottom line\n\n"
        f"Pick the {category} that fits your needs and budget — check current "
        "best-sellers below.\n"
    )
