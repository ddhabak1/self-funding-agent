"""Reachable-Places Research Agent.

"Find the best reachable places and promote there." This agent researches WHERE
to reach Indian Amazon buyers and ranks each channel by how many people it can
realistically reach AND how well that traffic converts to affiliate clicks.

It is honest about platform rules (this is what keeps the accounts — and the
income — alive):
  * Instagram/TikTok captions can't carry clickable links -> funnel via the
    on-site landing page (link in bio / pinned), never raw affiliate links.
  * YouTube & Pinterest allow links and convert well for shopping intent.
  * Reddit/Quora reward genuine help, punish spam -> value-first angles only.

Output: a nightly reach plan (state/reach_plan.json) the distributor uses to
tailor content per channel.
"""
import json
from datetime import datetime, timezone

from . import bus, config

NAME = "reach-agent"
_PLAN_PATH = config.STATE_DIR / "reach_plan.json"

# reach   = audience size potential for Indian shoppers (0-1)
# convert = how well its traffic turns into affiliate clicks/sales (0-1)
# clickable = captions allow a clickable outbound link (affects funnel design)
_CHANNELS = {
    "youtube_shorts": {"reach": 0.95, "convert": 0.55, "clickable": True,
        "note": "Massive in India; description links allowed; buyer intent."},
    "instagram_reels": {"reach": 0.90, "convert": 0.45, "clickable": False,
        "note": "Huge reach; funnel via link-in-bio to the landing page."},
    "facebook_reels": {"reach": 0.80, "convert": 0.45, "clickable": True,
        "note": "Older buyers with money; groups + reels; links allowed."},
    "pinterest": {"reach": 0.70, "convert": 0.75, "clickable": True,
        "note": "Evergreen shopping intent; pins link straight to landing."},
    "youtube_community": {"reach": 0.5, "convert": 0.5, "clickable": True,
        "note": "Warm existing subscribers."},
    "telegram": {"reach": 0.6, "convert": 0.6, "clickable": True,
        "note": "Free public channels; deal-hunter audience; links allowed."},
    "whatsapp_status": {"reach": 0.55, "convert": 0.6, "clickable": True,
        "note": "High trust, warm network; broadcast deals."},
    "reddit": {"reach": 0.6, "convert": 0.5, "clickable": True,
        "note": "r/IndianGaming, r/india etc.; value-first, no spam."},
    "quora": {"reach": 0.65, "convert": 0.6, "clickable": True,
        "note": "Answers rank on Google for years; buyer questions."},
    "x_twitter": {"reach": 0.6, "convert": 0.4, "clickable": True,
        "note": "Trend-jacking + threads; links allowed."},
    "pinterest_idea": {"reach": 0.5, "convert": 0.55, "clickable": False,
        "note": "Idea pins for reach; funnel via profile link."},
    "seo_blog": {"reach": 0.85, "convert": 0.7, "clickable": True,
        "note": "The owned site itself; compounding Google traffic."},
}


def rank_channels(top=6):
    """Channels sorted by reach x conversion (the promotion priority order)."""
    scored = sorted(_CHANNELS.items(),
                    key=lambda kv: kv[1]["reach"] * kv[1]["convert"],
                    reverse=True)
    return [{"channel": k,
             "score": round(v["reach"] * v["convert"], 3),
             "clickable": v["clickable"], "note": v["note"]}
            for k, v in scored[:top]]


def plan(brain, products, top=6):
    """Build tonight's reach plan: best channels + a per-category angle."""
    channels = rank_channels(top)
    cats = []
    for p in products[:5]:
        c = (p.get("category") if isinstance(p, dict) else "") or ""
        if c and c not in cats:
            cats.append(c)

    angles = {}
    if brain is not None and cats:
        prompt = (
            "For each product category below, give ONE punchy, honest content "
            "angle that makes Indian shoppers want to click through and buy on "
            "Amazon (curiosity + real value, no clickbait lies). Categories: "
            f"{', '.join(cats)}. Return strict JSON: "
            '{"angles": {"<category>": "<angle>"}}')
        try:
            data = brain.think(prompt, as_json=True)
            if isinstance(data, dict):
                angles = data.get("angles", {}) or {}
        except Exception:
            angles = {}

    plan_obj = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "channels": channels,
        "category_angles": angles,
        "priority": [c["channel"] for c in channels],
    }
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    _PLAN_PATH.write_text(json.dumps(plan_obj, indent=2, ensure_ascii=False))
    bus.set_intel("reach_plan", {"priority": plan_obj["priority"]})
    bus.post(NAME, "reach_planned",
             {"channels": plan_obj["priority"], "cats": cats})
    return plan_obj


def load_plan():
    if _PLAN_PATH.exists():
        try:
            return json.loads(_PLAN_PATH.read_text())
        except Exception:
            return None
    return None


def angle_for(category):
    p = load_plan() or {}
    return (p.get("category_angles") or {}).get(category, "")
