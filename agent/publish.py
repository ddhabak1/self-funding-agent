"""Publishes posts as Markdown to docs/ for free GitHub Pages hosting."""
import json
import re
from datetime import datetime, timezone

from . import config


def _date():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def publish(post):
    config.POSTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9-]", "", post["slug"].lower()) or "post"
    fname = f"{_date()}-{slug}.md"
    path = config.POSTS_DIR / fname

    tags = ", ".join(post.get("tags", []))
    front = (
        f"# {post['title']}\n\n"
        f"*Published {_date()} · Tags: {tags}*\n\n"
    )
    footer = _affiliate_footer()
    path.write_text(front + post["body"].strip() + footer)
    rebuild_index()
    return path


def _affiliate_footer():
    if not config.AFFILIATE_TAG:
        return "\n\n---\n*Support this AI: monetization not yet configured.*\n"
    return (
        f"\n\n---\n*As an affiliate ({config.AFFILIATE_TAG}) this site may "
        "earn from qualifying purchases.*\n"
    )


def rebuild_index():
    posts = sorted(config.POSTS_DIR.glob("*.md"), reverse=True)
    lines = [f"# {config.SITE_TITLE}\n", f"> {config.SITE_TAGLINE}\n", "## Posts\n"]
    for p in posts:
        title = p.read_text().splitlines()[0].lstrip("# ").strip()
        lines.append(f"- [{title}](posts/{p.name})")
    if len(lines) == 3:
        lines.append("_No posts yet._")
    (config.DOCS_DIR / "index.md").write_text("\n".join(lines) + "\n")
