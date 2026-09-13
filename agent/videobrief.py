"""OpenMontage render-brief handoff.

The money agent runs headless 24x7 and MUST always ship a video, so the built-in
PIL renderer (agent/shorts.py) stays the guaranteed $0 deliverable. OpenMontage
(https://github.com/calesthio/OpenMontage) is a far richer, instruction-driven
video studio (Remotion + Piper TTS + open footage) whose agentic pipeline is
meant to be *driven by an AI assistant* — not called as a one-shot CLI. That is
a mismatch for a fully unattended cron job.

The honest, working bridge: when VIDEO_BACKEND=openmontage we serialize a
structured "render brief" describing exactly what to produce (pipeline, script,
captions, CTA, style, output slug). The operator's 24x7 machine — where Claude
Code + ruflo drive OpenMontage through its clip-factory / cinematic pipeline —
picks these briefs up from state/video_briefs/ and produces the premium cut,
replacing the built-in short when ready.

This keeps CI $0 and always-shipping, while letting earnings fund progressively
better promo videos with no change to the rest of the agent.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from . import config

# clip-factory suits short social promos; cinematic for hero/pinned pieces.
_DEFAULT_PIPELINE = "clip-factory"


def _brief_dir() -> Path:
    d = config.VIDEO_BRIEF_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def emit_brief(*, slug, title, product, category, style, style_directive,
               script, landing_url, search_url):
    """Write a render brief OpenMontage can consume. Returns its path or None.

    Non-fatal by design: any failure just means we ship the built-in short.
    """
    if config.VIDEO_BACKEND != "openmontage":
        return None
    try:
        segments = []
        if isinstance(script, dict):
            for seg in script.get("scenes") or script.get("segments") or []:
                if isinstance(seg, dict):
                    segments.append(seg.get("text") or seg.get("caption") or "")
                else:
                    segments.append(str(seg))
        brief = {
            "schema": "openmontage.render_brief/1",
            "created": datetime.now(timezone.utc).isoformat(),
            "pipeline": _DEFAULT_PIPELINE,
            "unattended": True,
            "checkpoint_policy": "auto",
            "aspect_ratio": "9:16",
            "target_platforms": ["youtube_shorts", "instagram_reels",
                                  "facebook_reels"],
            "output_slug": slug,
            "title": title,
            "product": product,
            "category": category,
            "style": style,
            "style_directive": style_directive,
            "tts": {"provider": "piper", "offline": True},
            "footage": {"sources": ["archive_org", "wikimedia", "nasa",
                                     "pexels", "unsplash", "pixabay"],
                        "keys_required": False},
            "captions": {"word_level": True},
            "script": script,
            "segments": [s for s in segments if s],
            "call_to_action": {
                "text": "Full guide + today's best deals in the description",
                "landing_url": landing_url,
                "search_url": search_url,
            },
            "compliance": {
                "affiliate_links_in_caption": False,
                "ftc_disclosure_on_landing": True,
            },
            "openmontage_dir": config.OPENMONTAGE_DIR,
        }
        path = _brief_dir() / f"{slug}.json"
        path.write_text(json.dumps(brief, indent=2), encoding="utf-8")
        return path
    except Exception:
        return None
