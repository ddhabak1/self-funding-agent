"""Decides what to write, then writes it. This is the 'earning' engine."""
import json
import random

from . import config
from .brain import Brain


TOPIC_SEED = [
    "practical AI tools for small businesses",
    "beginner guides to personal productivity",
    "budget tech reviews and comparisons",
    "how-to tutorials for common software",
    "explainers on emerging technology",
]


def pick_topic(brain, memory):
    """Ask the brain for a fresh, monetizable topic, avoiding repeats."""
    recent = ", ".join(memory.get("recent_titles", [])[-10:]) or "none yet"
    seed = random.choice(TOPIC_SEED)
    prompt = f"""You are a content strategist for a blog about "{seed}".
Propose ONE specific, SEO-friendly article idea that could attract search
traffic and support affiliate/ad revenue. Avoid these recent titles: {recent}.
Return strict JSON: {{"title": "...", "slug": "kebab-case", "tags": ["..."],
"angle": "one sentence on why it earns"}}."""
    idea = brain.think(prompt, as_json=True)
    return idea


def write_article(brain, idea):
    """Generate the full post body from an idea."""
    title = idea.get("title", "Untitled")
    prompt = f"""Write a helpful, original ~600-word blog post titled "{title}".
Use clear Markdown with H2 sections, be genuinely useful, and where natural
suggest categories of products/tools (no fake links). End with a short
call-to-action. Do not fabricate statistics. Return only the Markdown body."""
    body = brain.think(prompt)
    return body


def create_content(brain, memory):
    idea = pick_topic(brain, memory)
    body = write_article(brain, idea)
    return {
        "title": idea.get("title", "Untitled"),
        "slug": idea.get("slug") or _slug(idea.get("title", "post")),
        "tags": idea.get("tags", []),
        "body": body,
    }


def _slug(text):
    return "-".join(
        "".join(c for c in text.lower() if c.isalnum() or c == " ").split()
    )[:60] or "post"
