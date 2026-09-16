"""Content & Video Factory.

Turns one scouted product into a full monetized asset pair:
  1. an on-site landing article with tagged Amazon affiliate links
     (Amazon requires affiliate links live on your own site, not pasted raw
     into social captions — so social drives traffic to these pages), and
  2. a top-notch HD vertical promo SHORT built in a bandit-chosen viral style,
     whose end card + description point viewers to that landing page.

Every asset is logged for the self-tuning optimizer so the system learns which
styles and categories actually earn clicks.
"""
import hashlib
import json
import os
from datetime import datetime, timezone

from . import bus, config, optimize
from .affiliate import recommend, search_link
from .publish import publish

NAME = "factory-agent"


def _asset_id(product, style):
    raw = f"{datetime.now(timezone.utc).strftime('%Y%m%d')}-{product}-{style}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _landing_post(brain, product, style_directive):
    """Write a persuasive, SEO landing article whose job is link clicks."""
    try:
        from .reflect import guidance
        learned = guidance()
    except Exception:
        learned = ""
    learned_line = (f"\nApply what has worked before: {learned}"
                    if learned else "")
    prompt = f"""Write an original, genuinely useful ~600-word buyer's guide
for people shopping for "{product}" on Amazon India. {style_directive}{learned_line}
Use Markdown H2 sections: what to look for, top features that matter, common
mistakes, and who each tier (budget / mid / premium) suits. Be specific and
honest; do NOT invent fake brands, prices or statistics. Keep it skimmable.
End with a punchy 1-line call to action to check current best-sellers.
Return only the Markdown body."""
    body = brain.think(prompt)
    if not body or body.startswith("[offline]"):
        body = (f"## The quick guide to buying {product}\n\n"
                f"Focus on real needs, build quality and value. Compare a "
                f"budget, mid-range and premium {product} before you decide.\n\n"
                f"## What to look for\n\n- Fit for your actual use\n"
                f"- Reliability and warranty\n- Genuine reviews, not hype\n\n"
                f"## Bottom line\n\nPick the {product} that matches your needs "
                f"and check today's best-sellers below.\n")
    return body


def make_asset(brain, product, style=None, affiliate_link=None):
    """Produce landing post (+video script/meta) for one product.

    affiliate_link: when the operator has pasted their own approved
    affiliate URL for this exact product (via the admin UI), use it verbatim
    for the primary CTA / "Where to buy" links instead of the auto-generated
    tagged search link. Falls back to the generic search link when omitted.
    """
    prod = product["product"] if isinstance(product, dict) else str(product)
    category = product.get("category", "") if isinstance(product, dict) else ""
    search_q = product.get("search_query", prod) if isinstance(product, dict) \
        else prod
    opportunity = product.get("opportunity", 0) if isinstance(product, dict) \
        else 0

    if style is None:
        style, directive = optimize.pick_style()
    else:
        directive = optimize.HOOK_STYLES.get(style, "")

    title = _title_for(prod, style)
    body = _landing_post(brain, prod, directive)
    buy_url = affiliate_link or search_link(search_q)
    # Conversion CTA up top — the first thing a reader sees drives the click.
    cta = (f"> 💡 **In a hurry?** See the current best-value **"
           f"[{prod}]({buy_url})** deals on Amazon "
           f"India — updated daily.\n\n")
    body = cta + body
    body += (f"\n\n## Where to buy\n\nBrowse current best-sellers and live "
             f"deals for **[{prod}]({buy_url})** on Amazon.\n")
    body += recommend(brain, title, body)

    post = {"title": title, "slug": _slug(prod, style),
            "tags": _tags(prod, category), "body": body}
    path = publish(post)

    asset_id = _asset_id(prod, style)
    result = {
        "id": asset_id, "product": prod, "category": category,
        "style": style, "opportunity": opportunity,
        "post": path.name, "video": None, "buy_url": buy_url,
        "manual_link": bool(affiliate_link),
        "created": datetime.now(timezone.utc).isoformat(),
    }

    # Build the promo video (heavy). Non-fatal if the renderer is unavailable.
    if os.environ.get("FACTORY_NO_VIDEO") == "1":
        bus.post(NAME, "video_skipped", {"product": prod, "err": "disabled"})
    else:
        try:
            from .shorts import make_script, build_from_script
            script = make_script(brain, title, body)
            _apply_style(script, directive)
            mp4 = build_from_script(script, path.stem)
            result["video"] = str(mp4.relative_to(config.ROOT))
            bus.post(NAME, "video_ready",
                     {"product": prod, "style": style, "file": mp4.name})
            # Optionally hand a richer render brief to the OpenMontage studio.
            try:
                from .videobrief import emit_brief
                brief = emit_brief(
                    slug=path.stem, title=title, product=prod,
                    category=category, style=style, style_directive=directive,
                    script=script, landing_url=f"/{path.stem}.html",
                    search_url=search_link(search_q))
                if brief:
                    result["video_brief"] = str(brief.relative_to(config.ROOT))
                    bus.post(NAME, "video_brief_queued",
                             {"product": prod, "brief": brief.name})
            except Exception as e:
                bus.post(NAME, "video_brief_skipped", {"err": str(e)[:120]})
        except Exception as e:
            bus.post(NAME, "video_skipped",
                     {"product": prod, "err": str(e)[:120]})

    optimize.log_asset(result)
    bus.post(NAME, "asset_built",
             {"product": prod, "style": style, "post": path.name,
              "video": bool(result["video"])})
    return result


def make_marketing_asset(brain, product, style=None, affiliate_link=None):
    """Produce a video + marketing image for one product — NO text article,
    NO on-site publish. The video/image CTA points straight at the given (or
    auto-generated) affiliate link, since Amazon Associates lets links live in
    a video/description or your own approved property, not only a website.
    """
    prod = product["product"] if isinstance(product, dict) else str(product)
    category = product.get("category", "") if isinstance(product, dict) else ""
    search_q = product.get("search_query", prod) if isinstance(product, dict) \
        else prod
    opportunity = product.get("opportunity", 0) if isinstance(product, dict) \
        else 0

    if style is None:
        style, directive = optimize.pick_style()
    else:
        directive = optimize.HOOK_STYLES.get(style, "")

    title = _title_for(prod, style)
    buy_url = affiliate_link or search_link(search_q)
    # Short descriptive source text for the video script (never published).
    body = _landing_post(brain, prod, directive)
    slug = _slug(prod, style)

    asset_id = _asset_id(prod, style)
    result = {
        "id": asset_id, "product": prod, "category": category,
        "style": style, "opportunity": opportunity,
        "video": None, "image": None, "buy_url": buy_url,
        "manual_link": bool(affiliate_link),
        "created": datetime.now(timezone.utc).isoformat(),
    }

    try:
        from .shorts import make_script, make_thumbnail, build_from_script
        script = make_script(brain, title, body, buy_url=buy_url)
        _apply_style(script, directive)

        thumb = make_thumbnail(script, slug)
        result["image"] = str(thumb.relative_to(config.ROOT))
        bus.post(NAME, "image_ready", {"product": prod, "file": thumb.name})

        if os.environ.get("FACTORY_NO_VIDEO") == "1":
            bus.post(NAME, "video_skipped", {"product": prod, "err": "disabled"})
        else:
            mp4 = build_from_script(script, slug)
            result["video"] = str(mp4.relative_to(config.ROOT))
            bus.post(NAME, "video_ready",
                     {"product": prod, "style": style, "file": mp4.name})
            try:
                from .videobrief import emit_brief
                brief = emit_brief(
                    slug=slug, title=title, product=prod,
                    category=category, style=style, style_directive=directive,
                    script=script, landing_url=buy_url,
                    search_url=buy_url)
                if brief:
                    result["video_brief"] = str(brief.relative_to(config.ROOT))
                    bus.post(NAME, "video_brief_queued",
                             {"product": prod, "brief": brief.name})
            except Exception as e:
                bus.post(NAME, "video_brief_skipped", {"err": str(e)[:120]})
    except Exception as e:
        bus.post(NAME, "asset_skipped", {"product": prod, "err": str(e)[:120]})

    optimize.log_asset(result)
    bus.post(NAME, "asset_built",
             {"product": prod, "style": style,
              "video": bool(result["video"]), "image": bool(result["image"])})
    return result



def _apply_style(script, directive):
    """Nudge the video script toward the chosen viral hook style."""
    if directive and isinstance(script, dict):
        script["style_note"] = directive


_STYLE_PREFIX = {
    "shock_stat": "The Numbers Don't Lie:",
    "mistake_warning": "Don't Buy",
    "before_after": "This Changed Everything:",
    "myth_bust": "The Truth About",
    "countdown": "Top 3",
    "question_hook": "Is This The Best",
    "secret_reveal": "The Secret To",
    "price_shock": "You Won't Believe The Price:",
}


def _title_for(product, style):
    p = product[:1].upper() + product[1:]
    pre = _STYLE_PREFIX.get(style, "Best")
    year = datetime.now(timezone.utc).year
    if style == "question_hook":
        return f"{pre} {p}? ({year} Buyer's Guide)"
    if style == "mistake_warning":
        return f"{pre} a {p} Before Reading This ({year})"
    if style == "countdown":
        return f"{pre} {p} Picks Worth Buying in {year}"
    return f"{pre} {p} — {year} Buyer's Guide"


def _slug(product, style):
    base = "-".join("".join(c for c in product.lower()
                    if c.isalnum() or c == " ").split())
    return f"{base}-{style}"[:60] or "post"


def _tags(product, category):
    tags = [w for w in product.lower().split() if len(w) > 2][:4]
    if category:
        tags.append(category.lower())
    tags += ["buying guide", str(datetime.now(timezone.utc).year)]
    # de-dup, keep order
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:6]
