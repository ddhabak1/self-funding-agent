"""HTTP application-server front-end for the agent.

Most PaaS "application servers" (Render, Railway, Google Cloud Run, App Engine,
Azure App Service, Heroku-style dynos) expect a process that **binds $PORT and
answers health checks** — not a bare background loop. This module is that
adapter, built on the Python standard library only (zero new dependencies):

  GET  /            -> tiny HTML status dashboard
  GET  /health      -> JSON vitals (for the platform's health probe)  [200/503]
  GET  /status      -> JSON: balance, strategy generation, guidance, recent bus
  POST /run?mode=   -> kick off one cycle|night run in the background

It also (by default) auto-starts the autonomous loop in a background thread, so
the same instance is BOTH a healthy web service AND the 24x7 worker. Set
SERVER_AUTORUN=0 to make it purely on-demand (trigger via /run).

Run it:  PORT=8080 python -m agent.server
"""
import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import bus, config, ledger, optimize, reflect, selfheal

# --- shared run state ------------------------------------------------------
_run_lock = threading.Lock()
_state = {"running": False, "last_mode": None, "last_started": None,
          "last_finished": None, "last_result": None, "runs": 0}
_brain = None


def _get_brain():
    global _brain
    if _brain is None:
        from .brain import Brain
        _brain = Brain()
    return _brain


def _do_run(mode):
    """Execute one run. Guarded so only one runs at a time."""
    if not _run_lock.acquire(blocking=False):
        return {"ok": False, "error": "a run is already in progress"}
    try:
        _state.update(running=True, last_mode=mode,
                      last_started=datetime.now(timezone.utc).isoformat())
        if mode == "night":
            from .night import run_night
            rc = run_night()
        else:
            from .orchestrator import run_cycle
            rc = run_cycle(make_short=os.environ.get("MAKE_SHORT", "0") == "1")
        result = {"ok": rc == 0, "rc": rc}
    except Exception as e:  # never let a run crash the server
        selfheal.record_incident("server_run", e)
        result = {"ok": False, "error": str(e)[:200]}
    finally:
        _state.update(running=False,
                      last_finished=datetime.now(timezone.utc).isoformat(),
                      last_result=result, runs=_state["runs"] + 1)
        _run_lock.release()
    return result


def _run_async(mode):
    t = threading.Thread(target=_do_run, args=(mode,), daemon=True)
    t.start()


def _autorun_loop():
    """Background 24x7 worker: keep running the night loop with a short rest.

    Also keeps the free/keyless OmniRoute router alive on this instance —
    without it, every call falls straight through to the Gemini SDK, which
    has a tiny daily quota (config.DAILY_CALL_BUDGET) and 429s within minutes
    of continuous use, silently degrading a 24x7 run to templated offline
    fallback content for the rest of the day.
    """
    mode = os.environ.get("SERVER_RUN_MODE", "night")
    rest = int(os.environ.get("SERVER_REST_SECONDS", "300"))
    # Continuous hosts should grind, not do tiny CI-sized batches — default
    # these up (still overridable via env) so the agent behaves as a true
    # 24x7 worker out of the box, matching agent/watchdog.py's defaults.
    os.environ.setdefault("NIGHT_HOURS", "0")
    os.environ.setdefault("NIGHT_MAX_ASSETS", "48")
    os.environ.setdefault("NIGHT_PACE_SECONDS", "180")
    time.sleep(3)  # let the web server bind first
    while True:
        try:
            from .watchdog import ensure_omniroute
            ensure_omniroute()
        except Exception as e:
            selfheal.record_incident("server_autorun_omniroute", e)
        try:
            _do_run(mode)
        except Exception as e:
            selfheal.record_incident("server_autorun", e)
        time.sleep(max(30, rest))


# --- payload builders ------------------------------------------------------
def _health():
    report = selfheal.check_health(_get_brain())
    return report


def _status():
    try:
        strat = optimize.load_strategy()
    except Exception:
        strat = {"generation": 0}
    posts = config.ROOT / "docs" / "posts"
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "balance": round(ledger.balance(), 4),
        "solvent": ledger.is_solvent(),
        "strategy_generation": strat.get("generation", 0),
        "guidance": reflect.guidance(),
        "posts": len(list(posts.glob("*.md"))) if posts.exists() else 0,
        "run": {k: _state[k] for k in
                ("running", "last_mode", "last_started",
                 "last_finished", "last_result", "runs")},
        "recent_bus": [f"{m['sender']} -> {m['topic']}" for m in bus.recent(8)],
    }


def _dashboard_html():
    s = _status()
    h = _health()
    healthy = h.get("healthy")
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>Self-Funding Agent</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>body{{font-family:system-ui,Segoe UI,Arial;margin:2rem;max-width:780px}}
code,pre{{background:#f4f4f5;padding:.15rem .35rem;border-radius:4px}}
.badge{{padding:.2rem .6rem;border-radius:999px;color:#fff;font-weight:600}}
.ok{{background:#16a34a}}.bad{{background:#dc2626}}</style></head><body>
<h1>Self-Funding Agent</h1>
<p>Status: <span class="badge {'ok' if healthy else 'bad'}">
{'HEALTHY' if healthy else 'DEGRADED'}</span>
&nbsp; balance <b>${s['balance']}</b> &nbsp; strategy gen <b>{s['strategy_generation']}</b>
&nbsp; posts <b>{s['posts']}</b></p>
<p><b>Currently running:</b> {s['run']['running']} (total runs: {s['run']['runs']})</p>
<p><b>Learned guidance:</b> {s['guidance'] or '(learning…)'}</p>
<h3>Recent activity</h3><pre>{chr(10).join(s['recent_bus']) or '—'}</pre>
<h3>Trigger a run</h3>
<pre>curl -X POST "$URL/run?mode=cycle"    # one article
curl -X POST "$URL/run?mode=night"    # scout+swarm+videos</pre>
<p>Endpoints: <code>/health</code> · <code>/status</code> · <code>/run</code></p>
<p><a href="/admin">Admin panel</a> — approve products, paste your affiliate
links, publish + market.</p>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):  # quiet default logging
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/admin"):
            from . import webui
            webui.handle(self, "GET", path, parse_qs(parsed.query))
        elif path in ("/health", "/healthz", "/livez", "/readyz"):
            report = _health()
            self._send(200 if report.get("healthy") else 503,
                       json.dumps(report))
        elif path == "/status":
            self._send(200, json.dumps(_status()))
        elif path in ("/", "/index.html"):
            self._send(200, _dashboard_html(), "text/html; charset=utf-8")
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/admin"):
            from . import webui
            webui.handle(self, "POST", parsed.path, parse_qs(parsed.query))
        elif parsed.path == "/run":
            mode = (parse_qs(parsed.query).get("mode", ["cycle"])[0]).lower()
            if mode not in ("cycle", "night"):
                mode = "cycle"
            if _state["running"]:
                self._send(409, json.dumps(
                    {"ok": False, "error": "a run is already in progress"}))
                return
            _run_async(mode)
            self._send(202, json.dumps({"ok": True, "started": mode}))
        else:
            self._send(404, json.dumps({"error": "not found"}))


def serve():
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    if os.environ.get("SERVER_AUTORUN", "1") == "1":
        threading.Thread(target=_autorun_loop, daemon=True).start()
        print(f"[server] autonomous loop started "
              f"(mode={os.environ.get('SERVER_RUN_MODE', 'night')})")
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"[server] listening on http://{host}:{port} "
          f"(health: /health, status: /status, trigger: POST /run)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("[server] shutting down")
        httpd.shutdown()


if __name__ == "__main__":
    serve()
