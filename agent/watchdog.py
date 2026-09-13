"""24x7 Watchdog — supervises the agent on an always-on machine / VPS.

GitHub Actions caps a job at ~6h, so the *true* all-night, never-stop grind
belongs on a box you own. This watchdog is that supervisor. It:

  * makes sure the free OmniRoute brain is up (starts it if not),
  * runs the night loop, and
  * if the loop ever crashes or exits, restarts it with exponential backoff
    (capped), recording every restart so failures are visible.

Run it detached on your machine:

    nohup python -m agent.watchdog >> watchdog.log 2>&1 &

or under systemd / launchd for real durability. It is intentionally tiny and
dependency-free so it is the last thing standing when other parts wobble.
"""
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

from . import config

_BACKOFF_START = 5      # seconds
_BACKOFF_MAX = 300      # cap restart delay at 5 min
_OMNIROUTE_PROBE = config.OMNIROUTE_URL.rstrip("/") + "/models"


def _log(msg):
    print(f"[watchdog {datetime.now(timezone.utc).isoformat()}] {msg}",
          flush=True)


def _omniroute_up():
    try:
        req = urllib.request.Request(_OMNIROUTE_PROBE, method="GET")
        urllib.request.urlopen(req, timeout=5)
        return True
    except urllib.error.HTTPError:
        return True   # any HTTP response means the server is listening
    except Exception:
        return False


def ensure_omniroute():
    """Best-effort start of the free LLM router if it isn't already serving."""
    if _omniroute_up():
        return True
    if not (shutil_which("omniroute")):
        _log("omniroute not installed; brain will use Gemini/offline fallback")
        return False
    _log("omniroute down -> starting daemon")
    try:
        subprocess.Popen(["omniroute", "serve", "--daemon", "--no-open"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        _log(f"failed to start omniroute: {e}")
        return False
    for _ in range(20):
        if _omniroute_up():
            _log("omniroute is up")
            return True
        time.sleep(1)
    _log("omniroute did not come up in time; continuing with fallback")
    return False


def shutil_which(name):
    from shutil import which
    return which(name)


def run_forever():
    _log("watchdog starting")
    backoff = _BACKOFF_START
    env = dict(os.environ)
    env.setdefault("MODE", "night")
    # On a 24x7 box, actually grind all night rather than a small batch.
    env.setdefault("NIGHT_HOURS", os.environ.get("NIGHT_HOURS", "8"))
    while True:
        ensure_omniroute()
        started = time.time()
        _log(f"launching night loop (NIGHT_HOURS={env['NIGHT_HOURS']})")
        try:
            rc = subprocess.call([sys.executable, "-m", "agent.main"], env=env)
            _log(f"night loop exited rc={rc}")
        except Exception as e:
            _log(f"night loop crashed: {e}")
            rc = 1
        # If it ran a healthy long while, reset backoff; else grow it.
        if time.time() - started > 600:
            backoff = _BACKOFF_START
        else:
            backoff = min(_BACKOFF_MAX, backoff * 2)
        _log(f"restarting in {backoff}s")
        time.sleep(backoff)


if __name__ == "__main__":
    try:
        run_forever()
    except KeyboardInterrupt:
        _log("watchdog stopped by operator")
