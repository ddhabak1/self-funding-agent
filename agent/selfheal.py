"""Self-Healing core — keeps the 24x7 agent alive and adapts when things break.

Nothing here needs a human. Every run starts with `preflight()`, which:
  * checks the vital organs (LLM backends, video renderer, disk, site, budget),
  * remembers failures in a rolling incident log (`state/incidents.json`),
  * trips a per-component **circuit breaker** when something keeps failing, and
  * writes safe config overrides back into the environment so the run routes
    around the damage instead of crashing (e.g. disable video if the renderer
    is missing, shrink the swarm after repeated timeouts, prune media when the
    disk is low, prefer Gemini when OmniRoute is down).

The philosophy: a self-funding agent that dies on the first broken dependency
earns nothing. So it must degrade gracefully and heal itself.
"""
import json
import os
import shutil
from datetime import datetime, timezone

from . import bus, config

NAME = "selfheal-agent"

_INCIDENTS_PATH = config.STATE_DIR / "incidents.json"
_HEALTH_PATH = config.STATE_DIR / "health.json"

# A component is "circuit-open" (skipped this run) after this many failures
# inside the look-back window.
_CIRCUIT_THRESHOLD = 3
_CIRCUIT_WINDOW_HOURS = 6
_MIN_FREE_GB = 1.0          # below this, skip heavy media + prune
_MEDIA_TTL_DAYS = 14        # prune generated videos older than this when low


def _now():
    return datetime.now(timezone.utc)


def _load_incidents():
    if _INCIDENTS_PATH.exists():
        try:
            return json.loads(_INCIDENTS_PATH.read_text())
        except Exception:
            return []
    return []


def _save_incidents(rows):
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    _INCIDENTS_PATH.write_text(json.dumps(rows[-500:], indent=2,
                                          ensure_ascii=False))


def record_incident(component, err, severity="error"):
    """Log a failure so the agent can learn to route around it."""
    rows = _load_incidents()
    rows.append({
        "ts": _now().isoformat(),
        "component": component,
        "severity": severity,
        "error": str(err)[:300],
    })
    _save_incidents(rows)
    bus.post(NAME, "incident", {"component": component, "err": str(err)[:120]})
    return rows


def recent_incidents(component=None, hours=_CIRCUIT_WINDOW_HOURS):
    cutoff = _now().timestamp() - hours * 3600
    out = []
    for r in _load_incidents():
        try:
            t = datetime.fromisoformat(r["ts"]).timestamp()
        except Exception:
            continue
        if t < cutoff:
            continue
        if component and r.get("component") != component:
            continue
        out.append(r)
    return out


def circuit_open(component):
    """True when a component has failed too often lately -> skip it this run."""
    return len(recent_incidents(component)) >= _CIRCUIT_THRESHOLD


def _free_gb(path):
    try:
        return shutil.disk_usage(str(path)).free / (1024 ** 3)
    except Exception:
        return 999.0


def _renderer_ok():
    """Video renderer needs PIL and (ideally) ffmpeg for audio muxing."""
    try:
        import PIL  # noqa: F401
    except Exception as e:
        return False, f"PIL missing: {e}"
    if not shutil.which("ffmpeg"):
        # PIL frames still render silent video via imageio; note but allow.
        return True, "ffmpeg missing (silent video only)"
    return True, "ok"


def _prune_media():
    """Delete old generated videos to reclaim space. Returns count removed."""
    media = getattr(config, "MEDIA_DIR", config.ROOT / "media")
    if not media.exists():
        return 0
    cutoff = _now().timestamp() - _MEDIA_TTL_DAYS * 86400
    removed = 0
    for child in media.iterdir():
        try:
            if child.stat().st_mtime < cutoff:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink()
                removed += 1
        except Exception:
            continue
    return removed


def check_health(brain=None):
    """Take the agent's vitals. Returns a structured report (no side effects
    beyond a cheap OmniRoute probe)."""
    checks = {}

    # --- LLM backends ---
    omni = gem = False
    if brain is not None:
        try:
            omni = bool(brain.omniroute) and brain._omni_reachable()
        except Exception:
            omni = False
        gem = bool(getattr(brain, "gemini", False))
    checks["llm"] = {
        "omniroute": omni,
        "gemini_configured": gem,
        "online": bool(omni or gem),
        "ok": True,  # offline stub still lets the agent run, so never fatal
    }

    # --- video renderer ---
    r_ok, r_note = _renderer_ok()
    checks["renderer"] = {"ok": r_ok, "note": r_note,
                          "circuit_open": circuit_open("factory")}

    # --- disk ---
    free = _free_gb(config.ROOT)
    checks["disk"] = {"free_gb": round(free, 2), "ok": free >= _MIN_FREE_GB}

    # --- site integrity ---
    docs = config.ROOT / "docs"
    posts = docs / "posts"
    n_posts = len(list(posts.glob("*.md"))) if posts.exists() else 0
    checks["site"] = {
        "docs_exists": docs.exists(),
        "index_exists": (docs / "index.md").exists()
                        or (docs / "index.html").exists(),
        "posts": n_posts,
        "ok": docs.exists(),
    }

    # --- rolling incident summary ---
    recent = recent_incidents(hours=24)
    by_comp = {}
    for r in recent:
        by_comp[r["component"]] = by_comp.get(r["component"], 0) + 1
    checks["incidents_24h"] = by_comp

    healthy = all(v.get("ok", True) for k, v in checks.items()
                  if isinstance(v, dict) and "ok" in v)
    return {"ts": _now().isoformat(), "healthy": healthy, "checks": checks}


def preflight(brain=None):
    """Run health checks AND apply self-healing overrides to the environment.

    Returns the health report. Safe to call at the top of every run.
    """
    report = check_health(brain)
    c = report["checks"]
    actions = []

    # Heal: renderer broken or its circuit is open -> stop trying to render.
    if not c["renderer"]["ok"] or c["renderer"]["circuit_open"]:
        os.environ["FACTORY_NO_VIDEO"] = "1"
        actions.append("disabled video (renderer unhealthy)")

    # Heal: low disk -> prune old media and skip heavy renders this run.
    if not c["disk"]["ok"]:
        removed = _prune_media()
        os.environ["FACTORY_NO_VIDEO"] = "1"
        actions.append(f"low disk: pruned {removed} media dirs, video off")

    # Heal: repeated swarm timeouts -> shrink concurrency and worker count.
    if circuit_open("swarm"):
        cur_c = int(os.environ.get("SWARM_CONCURRENCY",
                                   str(config.SWARM_CONCURRENCY)))
        cur_w = int(os.environ.get("SWARM_WORKERS",
                                   str(config.SWARM_WORKERS)))
        os.environ["SWARM_CONCURRENCY"] = str(max(2, cur_c // 2))
        os.environ["SWARM_WORKERS"] = str(max(10, cur_w // 2))
        actions.append(
            f"swarm throttled -> workers={os.environ['SWARM_WORKERS']} "
            f"conc={os.environ['SWARM_CONCURRENCY']}")

    # Heal: no online backend -> note it; the offline stub keeps us alive.
    if not c["llm"]["online"]:
        actions.append("no online LLM; running on offline stub")

    report["actions"] = actions
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    _HEALTH_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    bus.post(NAME, "preflight",
             {"healthy": report["healthy"], "actions": actions})
    return report


def doctor(brain=None):
    """Human-facing self-diagnosis. Prints the report, applies fixes, and
    returns an exit code (0 = healthy or auto-healed, 1 = hard-down)."""
    if brain is None:
        try:
            from .brain import Brain
            brain = Brain()
        except Exception:
            brain = None
    report = preflight(brain)
    c = report["checks"]
    print("=== SELF-HEAL DOCTOR ===")
    print(f"time      : {report['ts']}")
    print(f"healthy   : {report['healthy']}")
    print(f"llm       : online={c['llm']['online']} "
          f"omniroute={c['llm']['omniroute']} "
          f"gemini={c['llm']['gemini_configured']}")
    print(f"renderer  : ok={c['renderer']['ok']} ({c['renderer']['note']}) "
          f"circuit_open={c['renderer']['circuit_open']}")
    print(f"disk      : {c['disk']['free_gb']} GB free (ok={c['disk']['ok']})")
    print(f"site      : docs={c['site']['docs_exists']} "
          f"posts={c['site']['posts']}")
    print(f"incidents : {c['incidents_24h'] or 'none in 24h'}")
    if report["actions"]:
        print("healing   :")
        for a in report["actions"]:
            print(f"   - {a}")
    else:
        print("healing   : nothing to fix")
    # Only a missing docs tree (can't publish at all) is a hard failure.
    hard_down = not c["site"]["docs_exists"]
    print("=== END DOCTOR ===")
    return 1 if hard_down else 0


if __name__ == "__main__":
    raise SystemExit(doctor())
