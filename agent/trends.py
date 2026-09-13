"""Trend / Virality Agent.

Reads the Research Agent's product targets from the bus and decides the single
most viral, monetizable content idea to produce next, avoiding recent repeats.
"""
import random

from . import bus

NAME = "trend-agent"


def run(brain, recent_titles):
    targets = bus.get_intel("product_targets", [])
    if not targets:
        targets = [{"category": "tech gadgets", "search_query": "tech gadgets",
                    "why": "", "heat": 5}]

    menu = "; ".join(f"{t['category']} (heat {t.get('heat')})" for t in targets)
    avoid = ", ".join(recent_titles[-10:]) or "none"
    prompt = f"""You are a viral content strategist. From these best-selling,
high-commission categories: {menu}
Pick the ONE with the best viral + earning potential right now and craft a
click-worthy article/short idea. Avoid these recent titles: {avoid}.
Return strict JSON:
{{"title": "SEO + curiosity driven title",
  "slug": "kebab-case-slug",
  "tags": ["3-6 tags"],
  "category": "chosen category",
  "search_query": "amazon search phrase for the product",
  "angle": "why this earns + goes viral (1 line)"}}"""
    idea = brain.think(prompt, as_json=True)

    if not isinstance(idea, dict) or not idea.get("title"):
        t = max(targets, key=lambda x: x.get("heat", 0))
        cat = t["category"]
        idea = {
            "title": f"Best {cat} to Buy in India (2026 Buyer's Guide)",
            "slug": _slug(f"best-{cat}-2026"),
            "tags": [cat.lower(), "buying guide", "2026"],
            "category": cat,
            "search_query": t.get("search_query", cat),
            "angle": t.get("why", "High demand + good commission."),
        }
    idea.setdefault("slug", _slug(idea["title"]))
    bus.set_intel("next_idea", idea)
    bus.post(NAME, "next_idea",
             {"title": idea["title"], "category": idea.get("category")})
    return idea


def _slug(text):
    return "-".join("".join(c for c in text.lower()
                    if c.isalnum() or c == " ").split())[:60] or "post"
