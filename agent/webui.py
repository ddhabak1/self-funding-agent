"""Admin control panel — human-in-the-loop product approval + publishing.

The night/factory pipeline is fully autonomous, but Amazon Associates links
must point at products the operator has actually approved (and, in practice,
you often want your own pre-built affiliate links rather than a generic
tagged search URL). This module adds a small authenticated web UI:

  GET  /admin                 -> today's top-10 scouted products, one text
                                 box per product to paste an approved
                                 affiliate link, "Publish" button.
  POST /admin/publish         -> saves the pasted links and kicks off content
                                 generation + marketing (factory + distribute)
                                 for every product that now has a link,
                                 in a background thread (non-blocking).
  GET  /admin/status.json     -> polls publish progress for the dashboard.
  GET  /admin/refresh         -> re-scouts a fresh top-10 for today.
  GET  /admin/login           -> "Sign in with Google" (OAuth2 redirect).
  GET  /admin/oauth/callback  -> Google OAuth2 callback.
  GET  /admin/logout          -> clears the session.

Auth: Google "Sign in with Google" (Authorization Code flow), verified via
Google's tokeninfo endpoint (no JWT library needed — Google validates the
signature/audience/expiry server-side for us). Only ADMIN_ALLOWED_EMAIL may
use the panel; the session is a signed cookie (HMAC-SHA256, stdlib only), so
this stays dependency-free like the rest of the server.

Setup (you must do this once, in your own Google Cloud project):
  1. console.cloud.google.com -> APIs & Services -> OAuth consent screen
     (External, testing is fine) -> add your email as a test user.
  2. Credentials -> Create Credentials -> OAuth client ID -> Web application.
     Authorized redirect URI: https://<your-host>/admin/oauth/callback
  3. Set env vars: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, ADMIN_ALLOWED_EMAIL
     (your Google account email — only this account may sign in).
Until these are set, /admin shows setup instructions instead of erroring.
"""
import base64
import hashlib
import hmac
import html
import json
import secrets
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote_plus, urlencode

from . import bus, config, distribute, optimize, scout, selfheal
from .factory import make_asset

_LINKS_PATH = config.STATE_DIR / "manual_links.json"
_PUBLISH_PATH = config.STATE_DIR / "manual_publish.json"
_SECRET_PATH = config.STATE_DIR / ".session_secret"
_SESSION_TTL = 7 * 86400  # 7 days

_brain = None
_brain_lock = threading.Lock()


def _get_brain():
    global _brain
    with _brain_lock:
        if _brain is None:
            from .brain import Brain
            _brain = Brain()
        return _brain


# --- tiny persistence helpers -----------------------------------------------
def _load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return default
    return default


def _save_json(path, data):
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _pid(product):
    return hashlib.sha1(product["product"].encode()).hexdigest()[:10]


def _today_products():
    products = scout.load_today()
    if not products:
        products = scout.run(_get_brain(), top_n=10)
    return products


# --- session signing (HMAC, stdlib only, no new deps) -----------------------
def _secret():
    if config.SESSION_SECRET:
        return config.SESSION_SECRET.encode()
    if _SECRET_PATH.exists():
        return _SECRET_PATH.read_text().strip().encode()
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    s = secrets.token_hex(32)
    _SECRET_PATH.write_text(s)
    return s.encode()


def _sign(payload):
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def _verify(token):
    try:
        raw, sig = token.split(".", 1)
        expected = hmac.new(_secret(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def _cookies(handler):
    raw = handler.headers.get("Cookie", "")
    out = {}
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            out[k] = v
    return out


def _current_email(handler):
    tok = _cookies(handler).get("admin_session")
    if not tok:
        return None
    payload = _verify(tok)
    if not payload:
        return None
    email = payload.get("email")
    if config.ADMIN_ALLOWED_EMAIL and email != config.ADMIN_ALLOWED_EMAIL:
        return None
    return email


def _origin(handler):
    host = handler.headers.get("Host", "localhost")
    scheme = "http" if host.startswith(("localhost", "127.0.0.1")) else "https"
    xfp = handler.headers.get("X-Forwarded-Proto")
    if xfp:
        scheme = xfp.split(",")[0].strip()
    return f"{scheme}://{host}"


# --- small HTTP helpers ------------------------------------------------------
def _send_html(handler, code, body_html):
    data = body_html.encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _redirect(handler, location, cookies=None):
    handler.send_response(303)
    handler.send_header("Location", location)
    for c in cookies or []:
        handler.send_header("Set-Cookie", c)
    handler.end_headers()


# --- OAuth: login / callback / logout ---------------------------------------
def _configured():
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)


def _not_configured_html(origin=""):
    redirect_uri = f"{origin}/admin/oauth/callback" if origin \
        else "https://<your-host>/admin/oauth/callback"
    return _page_html(
        "<h2>Admin UI setup required</h2>"
        "<p>Google sign-in isn't configured yet. In your own Google Cloud "
        "project:</p>"
        "<ol>"
        "<li>APIs &amp; Services → OAuth consent screen → add your email as "
        "a test user.</li>"
        "<li>Credentials → Create Credentials → OAuth client ID → Web "
        "application.<br>Authorized redirect URI: "
        f"<code>{html.escape(redirect_uri)}</code></li>"
        "<li>Set env vars <code>GOOGLE_CLIENT_ID</code>, "
        "<code>GOOGLE_CLIENT_SECRET</code>, <code>ADMIN_ALLOWED_EMAIL</code> "
        "(your Google account) on the host, then restart.</li>"
        "</ol>", email=None)


def _login(handler):
    if not _configured():
        _send_html(handler, 200, _not_configured_html(_origin(handler)))
        return
    state = secrets.token_urlsafe(24)
    redirect_uri = _origin(handler) + "/admin/oauth/callback"
    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "prompt": "select_account",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    handler.send_response(302)
    handler.send_header("Location", url)
    handler.send_header(
        "Set-Cookie",
        f"oauth_state={state}; Path=/; HttpOnly; Max-Age=600; SameSite=Lax")
    handler.end_headers()


def _oauth_callback(handler, query):
    if not _configured():
        _send_html(handler, 200, _not_configured_html(_origin(handler)))
        return
    code = (query.get("code") or [None])[0]
    state = (query.get("state") or [None])[0]
    if not code or not state or _cookies(handler).get("oauth_state") != state:
        _send_html(handler, 400,
                   _page_html("<h2>Login failed</h2><p>Invalid or expired "
                              "login attempt — try again.</p>", email=None))
        return
    redirect_uri = _origin(handler) + "/admin/oauth/callback"
    body = urlencode({
        "code": code, "client_id": config.GOOGLE_CLIENT_ID,
        "client_secret": config.GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    }).encode()
    try:
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token", data=body, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            tok = json.loads(resp.read().decode())
        id_token = tok.get("id_token", "")
        info_req = urllib.request.Request(
            "https://oauth2.googleapis.com/tokeninfo?id_token="
            + quote_plus(id_token))
        with urllib.request.urlopen(info_req, timeout=15) as resp:
            info = json.loads(resp.read().decode())
    except Exception as e:
        selfheal.record_incident("admin_oauth", e)
        _send_html(handler, 502,
                   _page_html(f"<h2>Login failed</h2><p>{html.escape(str(e)[:200])}"
                              "</p>", email=None))
        return

    email = info.get("email")
    verified = info.get("email_verified") in ("true", True)
    aud_ok = info.get("aud") == config.GOOGLE_CLIENT_ID
    allowed = (not config.ADMIN_ALLOWED_EMAIL
              or email == config.ADMIN_ALLOWED_EMAIL)
    if not (email and verified and aud_ok and allowed):
        _send_html(handler, 403,
                   _page_html("<h2>Access denied</h2><p>This Google account "
                              "isn't authorised for this admin panel.</p>",
                              email=None))
        return

    token = _sign({"email": email, "exp": time.time() + _SESSION_TTL})
    secure = "; Secure" if _origin(handler).startswith("https") else ""
    handler.send_response(302)
    handler.send_header("Location", "/admin")
    handler.send_header(
        "Set-Cookie",
        f"admin_session={token}; Path=/; HttpOnly; Max-Age={_SESSION_TTL}; "
        f"SameSite=Lax{secure}")
    handler.send_header("Set-Cookie", "oauth_state=; Path=/; Max-Age=0")
    handler.end_headers()


def _logout(handler):
    handler.send_response(302)
    handler.send_header("Location", "/admin/login")
    handler.send_header("Set-Cookie", "admin_session=; Path=/; Max-Age=0")
    handler.end_headers()


# --- dashboard ---------------------------------------------------------------
def _row_html(product, pid, link, status, info):
    name = html.escape(product.get("product", ""))
    cat = html.escape(product.get("category", ""))
    heat = product.get("heat", "")
    opp = product.get("opportunity", "")
    val = html.escape(link)
    badge = {"": "", "queued": "⏳ queued", "generating": "⚙️ generating…",
             "done": "✅ published", "error": "⚠️ error"}.get(status, status)
    extra = ""
    if status == "done" and info:
        post = info.get("landing_url") or info.get("post", "")
        if post:
            extra = f' · <a href="{html.escape(post)}" target="_blank">view</a>'
    elif status == "error" and info:
        extra = f' · <span class="err">{html.escape(str(info.get("error", ""))[:120])}</span>'
    disabled = "readonly" if status in ("queued", "generating", "done") else ""
    return f"""<tr>
  <td><b>{name}</b><br><small>{cat} · heat {heat} · opportunity {opp}</small></td>
  <td><input type="text" name="link_{pid}" value="{val}" {disabled}
       placeholder="Paste your approved Amazon affiliate link" size="42"></td>
  <td>{badge}{extra}</td>
</tr>"""


def _page_html(body, email):
    who = (f'<span class="who">{html.escape(email)} · '
          f'<a href="/admin/logout">sign out</a></span>' if email else "")
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>Admin — {html.escape(config.SITE_TITLE)}</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
body{{font-family:system-ui,Segoe UI,Arial;margin:2rem auto;max-width:900px;color:#1a1a1a}}
table{{width:100%;border-collapse:collapse;margin:1rem 0}}
td{{padding:.6rem;border-bottom:1px solid #e5e7eb;vertical-align:top}}
input[type=text]{{width:100%;padding:.4rem;border:1px solid #d1d5db;border-radius:6px}}
button{{background:#16a34a;color:#fff;border:0;padding:.6rem 1.2rem;border-radius:8px;
  font-weight:600;cursor:pointer}}
a.btn{{display:inline-block;margin-left:.6rem;color:#374151;text-decoration:none}}
.who{{float:right;font-size:.85rem;color:#6b7280}}
.err{{color:#dc2626}}
header{{overflow:auto;margin-bottom:1rem}}
code{{background:#f4f4f5;padding:.15rem .35rem;border-radius:4px}}
</style></head><body>
<header><h1 style="display:inline">Admin — {html.escape(config.SITE_TITLE)}</h1>{who}</header>
{body}
</body></html>"""


def _dashboard(handler):
    email = _current_email(handler)
    if not email:
        _redirect(handler, "/admin/login")
        return
    if not _configured():
        _send_html(handler, 200, _not_configured_html(_origin(handler)))
        return
    products = _today_products()
    links = _load_json(_LINKS_PATH, {})
    pub = _load_json(_PUBLISH_PATH, {})
    rows = []
    for p in products:
        pid = _pid(p)
        info = pub.get(pid, {})
        rows.append(_row_html(p, pid, links.get(pid, ""),
                              info.get("status", ""), info))
    body = f"""
<p>Today's top {len(products)} scouted products. Paste your own approved
Amazon affiliate link for any product you want promoted, then hit
<b>Publish &amp; start marketing</b> — the agent writes the buyer's guide
+ promo video and distributes it, using <i>your</i> link.</p>
<form method="post" action="/admin/publish">
<table>
<tr><th align=left>Product</th><th align=left>Your affiliate link</th><th align=left>Status</th></tr>
{''.join(rows) if rows else '<tr><td colspan=3>No products yet — hit refresh.</td></tr>'}
</table>
<button type="submit">Publish &amp; start marketing</button>
<a class="btn" href="/admin/refresh">↻ refresh product list</a>
</form>
<script>
// Poll status so "generating" rows flip to "published" without a full reload.
setInterval(function() {{
  fetch('/admin/status.json').then(r => r.json()).then(function(data) {{
    var needsReload = false;
    for (var k in data) {{ if (data[k].status === 'done' || data[k].status === 'error') needsReload = true; }}
  }});
}}, 8000);
</script>"""
    _send_html(handler, 200, _page_html(body, email))


def _refresh(handler):
    email = _current_email(handler)
    if not email:
        _redirect(handler, "/admin/login")
        return
    try:
        scout.run(_get_brain(), top_n=10)
    except Exception as e:
        selfheal.record_incident("admin_refresh", e)
    _redirect(handler, "/admin")


def _status_json(handler):
    email = _current_email(handler)
    if not email:
        handler._send(401, json.dumps({"error": "unauthorized"}))
        return
    handler._send(200, json.dumps(_load_json(_PUBLISH_PATH, {})))


# --- publish: save links + kick off generation in the background -----------
def _publish(handler):
    email = _current_email(handler)
    if not email:
        _redirect(handler, "/admin/login")
        return
    length = int(handler.headers.get("Content-Length", 0) or 0)
    raw = handler.rfile.read(length).decode() if length else ""
    form = parse_qs(raw)

    products = _today_products()
    links = _load_json(_LINKS_PATH, {})
    pub = _load_json(_PUBLISH_PATH, {})
    queued = []
    for p in products:
        pid = _pid(p)
        val = (form.get(f"link_{pid}") or [""])[0].strip()
        if val:
            links[pid] = val
        link = links.get(pid, "")
        already = pub.get(pid, {}).get("status")
        if link and already not in ("queued", "generating", "done"):
            pub[pid] = {"status": "queued", "product": p["product"]}
            queued.append((p, link, pid))
    _save_json(_LINKS_PATH, links)
    _save_json(_PUBLISH_PATH, pub)

    if queued:
        t = threading.Thread(target=_run_publish_jobs, args=(queued,),
                             daemon=True)
        t.start()
    _redirect(handler, "/admin")


def _run_publish_jobs(queued):
    brain = _get_brain()
    for product, link, pid in queued:
        pub = _load_json(_PUBLISH_PATH, {})
        pub[pid] = {"status": "generating", "product": product["product"]}
        _save_json(_PUBLISH_PATH, pub)
        try:
            style, _directive = optimize.pick_style()
            res = make_asset(brain, product, style=style, affiliate_link=link)
            try:
                dist = distribute.distribute(brain, res, product)
            except Exception as e:
                selfheal.record_incident("admin_publish_distribute", e)
                dist = {}
            pub = _load_json(_PUBLISH_PATH, {})
            pub[pid] = {
                "status": "done", "product": product["product"],
                "post": res.get("post"), "video": res.get("video"),
                "landing_url": dist.get("landing_url"),
                "finished": datetime.now(timezone.utc).isoformat(),
            }
            _save_json(_PUBLISH_PATH, pub)
            bus.post("admin-agent", "manual_publish",
                     {"product": product["product"], "pid": pid})
        except Exception as e:
            selfheal.record_incident("admin_publish", e)
            pub = _load_json(_PUBLISH_PATH, {})
            pub[pid] = {"status": "error", "product": product["product"],
                       "error": str(e)[:200]}
            _save_json(_PUBLISH_PATH, pub)
    try:
        distribute.build_feed_and_sitemap()
    except Exception as e:
        selfheal.record_incident("admin_publish_feeds", e)


# --- router -------------------------------------------------------------
def handle(handler, method, path, query):
    """Handle one /admin* request. Returns True (always handles what it owns)."""
    if path == "/admin/login" and method == "GET":
        _login(handler)
    elif path == "/admin/oauth/callback" and method == "GET":
        _oauth_callback(handler, query)
    elif path == "/admin/logout" and method == "GET":
        _logout(handler)
    elif path == "/admin/status.json" and method == "GET":
        _status_json(handler)
    elif path == "/admin/refresh" and method == "GET":
        _refresh(handler)
    elif path == "/admin/publish" and method == "POST":
        _publish(handler)
    elif path == "/admin" and method == "GET":
        _dashboard(handler)
    else:
        handler._send(404, json.dumps({"error": "not found"}))
    return True
