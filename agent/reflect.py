"""Self-Improvement reflection — the agent learns lessons and gets smarter.

The bandit in `optimize.py` tunes *which* hook style / category to pick. This
module closes a higher loop: after each night it **reflects** on everything it
has produced and earned, distills that into plain-language *lessons*, and feeds
those lessons back into future content prompts via `guidance()`.

Over many nights this compounds: the agent stops repeating what didn't work and
leans harder into what does — without a human ever editing a prompt.

Outputs:
  * state/lessons.json  — structured lessons (best/weak styles + categories,
                          video-vs-post signal, sample sizes, generation).
  * state/lessons.md    — the same, human-readable, committed so you can watch
                          the agent's strategy evolve over time.
"""
import json
from datetime import datetime, timezone

from . import bus, config, optimize

NAME = "reflect-agent"

_LESSONS_JSON = config.STATE_DIR / "lessons.json"
_LESSONS_MD = config.STATE_DIR / "lessons.md"


def _avg(arm):
    c = arm.get("count", 0)
    return (arm.get("reward", 0.0) / c) if c else 0.0


def _rank(d, top=3):
    ranked = sorted(d.items(), key=lambda kv: _avg(kv[1]), reverse=True)
    ranked = [(k, round(_avg(v), 3), v.get("count", 0)) for k, v in ranked
              if v.get("count", 0) > 0]
    return ranked[:top], ranked[-top:] if len(ranked) > top else []


def reflect(brain=None):
    """Mine performance + strategy into lessons. Returns the lessons dict."""
    strat = optimize.load_strategy()
    perf = optimize._load_perf()

    best_styles, weak_styles = _rank(strat.get("styles", {}))
    best_cats, weak_cats = _rank(strat.get("categories", {}))

    # Did producing a video correlate with better assets? (uses opportunity as
    # a proxy reward until real click metrics arrive.)
    vid = [e for e in perf if e.get("video")]
    novid = [e for e in perf if not e.get("video")]

    def _opp(rows):
        vals = [e.get("opportunity", 0) or 0 for e in rows]
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    lessons = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "generation": strat.get("generation", 0),
        "assets_seen": len(perf),
        "best_styles": best_styles,
        "weak_styles": weak_styles,
        "best_categories": best_cats,
        "weak_categories": weak_cats,
        "video": {"count": len(vid), "avg_opportunity": _opp(vid)},
        "post_only": {"count": len(novid), "avg_opportunity": _opp(novid)},
    }

    # A short, prompt-ready directive the content agents can inject.
    tips = []
    if best_cats:
        seen, cats = set(), []
        for k, _, _ in best_cats:
            key = k.strip().lower()
            if key and key not in seen:
                seen.add(key)
                cats.append(key)
        if cats:
            tips.append("lean into " + ", ".join(cats))
    if best_styles:
        tips.append("favor hooks that " +
                    optimize.HOOK_STYLES.get(best_styles[0][0], "grab attention")
                    .rstrip("."))
    if weak_styles:
        tips.append("avoid over-using the "
                    + weak_styles[0][0].replace("_", " ") + " angle")
    lessons["guidance"] = ("; ".join(tips) or
                           "keep exploring styles and categories") + "."

    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    _LESSONS_JSON.write_text(json.dumps(lessons, indent=2, ensure_ascii=False))
    _LESSONS_MD.write_text(_render_md(lessons))
    bus.set_intel("lessons", {"generation": lessons["generation"],
                              "guidance": lessons["guidance"]})
    bus.post(NAME, "reflected",
             {"generation": lessons["generation"],
              "assets_seen": lessons["assets_seen"]})
    return lessons


def guidance():
    """Short learned directive to inject into content prompts. Cheap + safe."""
    if _LESSONS_JSON.exists():
        try:
            return json.loads(_LESSONS_JSON.read_text()).get("guidance", "")
        except Exception:
            return ""
    return ""


def _render_md(l):
    def _fmt(rows):
        return "\n".join(f"- **{k}** — avg reward {a} (n={n})"
                         for k, a, n in rows) or "- (not enough data yet)"
    return (
        f"# What the agent has learned\n\n"
        f"_Updated {l['ts']} · generation {l['generation']} · "
        f"{l['assets_seen']} assets observed._\n\n"
        f"## Best hook styles\n{_fmt(l['best_styles'])}\n\n"
        f"## Best categories\n{_fmt(l['best_categories'])}\n\n"
        f"## Video vs. post\n"
        f"- with video: {l['video']['count']} assets, "
        f"avg opportunity {l['video']['avg_opportunity']}\n"
        f"- post only: {l['post_only']['count']} assets, "
        f"avg opportunity {l['post_only']['avg_opportunity']}\n\n"
        f"## Current guidance\n{l['guidance']}\n")


if __name__ == "__main__":
    import pprint
    pprint.pprint(reflect())
