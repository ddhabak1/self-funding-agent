"""Distribution / "share on the public internet" layer.

Producing content isn't enough — people have to SEE it and click the affiliate
funnel. This module turns every asset into platform-tailored share content and
pushes it out across the public internet, three ways:

  1. Content packs — per-channel title/caption/hashtags/hook engineered for
     click-through, funneling to the on-site landing page (compliant: no raw
     affiliate links in social captions, FTC #ad disclosure included).
  2. Auto-post — best-effort publishing to channels with FREE, key-optional
     APIs that ARE public: Telegram channel, Discord webhook, generic webhook
     (Zapier/IFTTT/Make -> Instagram/YouTube/Facebook). No-ops safely without
     credentials, so nothing breaks when tokens aren't set.
  3. Organic discovery — a real RSS feed + sitemap.xml + robots.txt on the
     site so Google/Bing and feed readers surface the content for free, 24x7.

Everything queued to state/distribution/ so a human or a token-holding poster
can fan it out to the platforms that need OAuth (Instagram/YouTube/Facebook).
"""
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from . import bus, config, reach

NAME = "distributor-agent"
_QUEUE_DIR = config.STATE_DIR / "distribution"

# Channels we prepare share copy for (matches reach.py catalog).
_CHANNELS = ["youtube_shorts", "instagram_reels", "facebook_reels",
             "pinterest", "telegram", "x_twitter", "reddit", "quora"]


def landing_url(slug):
    base = f"{config.SITE_URL}{config.SITE_BASEURL}".rstrip("/")
    return f"{base}/posts/{slug}.html"


# --- content packs ---------------------------------------------------------
def _hashtags(product, category):
    words = re.findall(r"[a-z0-9]+", f"{product} {category}".lower())
    tags = ["#" + w for w in words if len(w) > 2][:6]
    tags += ["#amazonfinds", "#amazonindia", "#techdeals", "#ad"]
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:10]


def _fallback_caption(title, product, url, angle):
    hook = angle or f"The smart way to pick a {product}"
    return (f"{hook} 👀\n\n"
            f"Full honest buyer's guide + today's best deals 👉 {url}\n\n"
            f"#ad As an Amazon Associate we earn from qualifying purchases.")


def content_pack(brain, asset, product):
    """Build per-channel share copy. Funnels to the landing page (compliant)."""
    slug = asset.get("post", "").replace(".md", "")
    prod = asset.get("product", product if isinstance(product, str) else "")
    category = asset.get("category", "")
    title = asset.get("title") or prod
    url = landing_url(slug)
    angle = reach.angle_for(category)

    caption = None
    if brain is not None:
        prompt = (
            f'Write a short, high-CTR social caption (max 45 words) promoting a '
            f'buyer\'s guide for "{prod}" that makes Indian shoppers want to '
            f'click through to buy on Amazon. Angle: "{angle or "value + honesty"}". '
            f'End by pointing to the link. Do NOT include any URL or hashtags '
            f'(added separately). Return only the caption text.')
        try:
            c = brain.think(prompt)
            if c and not c.startswith("[offline]"):
                caption = c.strip().strip('"')
        except Exception:
            caption = None

    tags = _hashtags(prod, category)
    base_caption = caption or (angle or f"How to choose the best {prod}")
    yt_title = (title if len(title) <= 90 else title[:87] + "...")
    pack = {
        "slug": slug, "product": prod, "landing_url": url,
        "channels": {
            "youtube_shorts": {
                "title": yt_title,
                "description": f"{base_caption}\n\nFull guide + best deals: {url}\n\n"
                               + " ".join(tags),
            },
            "instagram_reels": {  # not clickable -> funnel via bio/site
                "caption": f"{base_caption}\n\nLink in bio for the full guide + deals 🔗\n"
                           + " ".join(tags),
            },
            "facebook_reels": {
                "caption": f"{base_caption}\n\nGuide + deals: {url}\n" + " ".join(tags[:6]),
            },
            "pinterest": {
                "title": yt_title,
                "description": f"{base_caption} {' '.join(tags[:5])}",
                "destination_link": url,
            },
            "telegram": {"text": f"*{title}*\n{base_caption}\n\n[Full guide + deals]({url})"},
            "x_twitter": {"text": f"{base_caption}\n{url}\n" + " ".join(tags[:3])},
            "reddit": {  # value-first, no spam
                "title": f"{title} — my honest breakdown",
                "body": f"{base_caption}\n\nI wrote up the full comparison here: {url}\n\n"
                        f"(Heads up: contains affiliate links — #ad.)"},
            "quora": {"answer": f"{base_caption}\n\nI go deeper (with the specific things "
                                f"to check before buying) here: {url}"},
        },
        "created": datetime.now(timezone.utc).isoformat(),
    }
    return pack


def queue(pack):
    _QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    path = _QUEUE_DIR / f"{pack['slug']}.json"
    path.write_text(json.dumps(pack, indent=2, ensure_ascii=False))
    return path


# --- auto-post (free / key-optional, safe no-op without creds) -------------
def _post_json(url, payload, headers=None):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status


def auto_post(pack):
    """Publish to public channels that expose FREE APIs when a token is set."""
    posted = []
    text = pack["channels"]["telegram"]["text"]
    url = pack["landing_url"]

    # Telegram public channel — free Bot API, genuinely public sharing.
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if tok and chat:
        try:
            _post_json(f"https://api.telegram.org/bot{tok}/sendMessage",
                       {"chat_id": chat, "text": text,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": False})
            posted.append("telegram")
        except Exception as e:
            bus.post(NAME, "post_failed", {"channel": "telegram", "err": str(e)[:100]})

    # Discord webhook — free, public server channel.
    hook = os.environ.get("DISCORD_WEBHOOK_URL")
    if hook:
        try:
            _post_json(hook, {"content": f"**{pack['product']}** — {url}\n{text}"})
            posted.append("discord")
        except Exception as e:
            bus.post(NAME, "post_failed", {"channel": "discord", "err": str(e)[:100]})

    # Generic webhook -> Zapier/IFTTT/Make can fan out to IG/YouTube/FB.
    generic = os.environ.get("SOCIAL_WEBHOOK_URL")
    if generic:
        try:
            _post_json(generic, {"product": pack["product"],
                                 "landing_url": url, "pack": pack["channels"]})
            posted.append("webhook")
        except Exception as e:
            bus.post(NAME, "post_failed", {"channel": "webhook", "err": str(e)[:100]})

    return posted


# --- organic discovery: RSS + sitemap + robots ----------------------------
def _posts_meta():
    posts = sorted(config.POSTS_DIR.glob("*.md"), reverse=True)
    out = []
    for p in posts:
        title = p.stem
        try:
            for line in p.read_text().splitlines():
                m = re.match(r"title:\s*(.+)", line)
                if m:
                    title = m.group(1).strip().strip('"')
                    break
        except Exception:
            pass
        out.append((p.stem, title))
    return out


def build_feed_and_sitemap():
    """Write docs/feed.xml, docs/sitemap.xml, docs/robots.txt for free reach."""
    base = f"{config.SITE_URL}{config.SITE_BASEURL}".rstrip("/")
    metas = _posts_meta()
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    items = []
    for stem, title in metas[:50]:
        link = f"{base}/posts/{stem}.html"
        items.append(
            f"<item><title>{escape(title)}</title><link>{escape(link)}</link>"
            f"<guid>{escape(link)}</guid><pubDate>{now}</pubDate></item>")
    rss = (f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0">'
           f'<channel><title>{escape(config.SITE_TITLE)}</title>'
           f'<link>{escape(base)}/</link>'
           f'<description>{escape(config.SITE_TAGLINE)}</description>'
           f'{"".join(items)}</channel></rss>\n')

    urls = [f"<url><loc>{escape(base)}/</loc></url>"]
    for stem, _ in metas:
        urls.append(f"<url><loc>{escape(base)}/posts/{stem}.html</loc></url>")
    sitemap = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               f'{"".join(urls)}</urlset>\n')

    robots = ("User-agent: *\nAllow: /\n"
              f"Sitemap: {base}/sitemap.xml\n")

    config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (config.DOCS_DIR / "feed.xml").write_text(rss)
    (config.DOCS_DIR / "sitemap.xml").write_text(sitemap)
    (config.DOCS_DIR / "robots.txt").write_text(robots)
    bus.post(NAME, "feeds_built", {"posts": len(metas)})
    return len(metas)


# --- orchestration ---------------------------------------------------------
def distribute(brain, asset, product=None):
    """Full share pipeline for one asset: pack -> queue -> auto-post."""
    pack = content_pack(brain, asset, product)
    qpath = queue(pack)
    posted = auto_post(pack)
    bus.post(NAME, "distributed",
             {"slug": pack["slug"], "queued": qpath.name,
              "auto_posted": posted or "queued-only"})
    return {"queued": str(qpath.relative_to(config.ROOT)),
            "auto_posted": posted, "landing_url": pack["landing_url"]}
