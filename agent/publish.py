"""Publishes posts as SEO-ready Jekyll pages to docs/ for GitHub Pages."""
import json
import re
from datetime import datetime, timezone

from . import config


def _date():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _yaml(v):
    """Safely quote a scalar for YAML (JSON double-quoting is valid YAML)."""
    return json.dumps(v, ensure_ascii=False)


def _description(body, fallback):
    """First real text of the body, stripped of Markdown, ~155 chars."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)  # links -> text
    text = re.sub(r"[#*`>_]", "", text)
    text = " ".join(text.split())
    if not text:
        return fallback
    return (text[:152].rsplit(" ", 1)[0] + "...") if len(text) > 155 else text


def publish(post):
    config.POSTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9-]", "", post["slug"].lower()) or "post"
    fname = f"{_date()}-{slug}.md"
    path = config.POSTS_DIR / fname

    desc = _description(post["body"], config.SITE_TAGLINE)
    tags = post.get("tags", [])
    front_matter = (
        "---\n"
        "layout: default\n"
        f"title: {_yaml(post['title'])}\n"
        f"description: {_yaml(desc)}\n"
        f"date: {_date()}\n"
        f"tags: [{', '.join(_yaml(t) for t in tags)}]\n"
        "---\n\n"
    )
    heading = f"# {post['title']}\n\n*Published {_date()}*\n\n"
    footer = _affiliate_footer()
    path.write_text(front_matter + heading + post["body"].strip() + footer)
    rebuild_index()
    return path


def _affiliate_footer():
    if not config.AFFILIATE_TAG:
        return (
            "\n\n---\n*Disclosure: this site is reader-supported and may add "
            "affiliate links once monetization is configured.*\n"
        )
    return (
        "\n\n---\n*Disclosure: As an Amazon Associate and affiliate "
        f"({config.AFFILIATE_TAG}), this site earns from qualifying purchases "
        "at no extra cost to you.*\n"
    )


def rebuild_index():
    posts = sorted(config.POSTS_DIR.glob("*.md"), reverse=True)
    lines = [
        "---",
        "layout: default",
        f"title: {_yaml(config.SITE_TITLE)}",
        f"description: {_yaml(config.SITE_TAGLINE)}",
        "---",
        "",
        "## Latest posts",
        "",
    ]
    for p in posts:
        lines.append(f"- [{_title_of(p)}](posts/{p.name})")
    if not posts:
        lines.append("_No posts yet._")
    (config.DOCS_DIR / "index.md").write_text("\n".join(lines) + "\n")


def _title_of(path):
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem
