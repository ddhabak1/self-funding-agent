"""The shared 'brain' — a backend-agnostic LLM wrapper hardened for 24x7 use.

Backends (chosen via config.LLM_BACKEND):
  - OmniRoute: a local OpenAI-compatible router that aggregates many free /
    keyless providers with automatic fallback. Preferred because it does NOT
    burn the limited Gemini free-tier quota (no more 429 storms).
  - Gemini SDK: the classic direct Google Gemini path (supports live Google
    Search grounding for research).
  - Offline stub: so the pipeline never hard-fails.

Features:
  - retry with exponential backoff on transient/429 errors
  - a per-day call budget so continuous running won't blow a free quota
  - optional Google Search grounding (Gemini backend only)
  - graceful degradation across backends, then to an offline stub
"""
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import config

try:
    from google import genai
    from google.genai import types
    _HAS_SDK = True
except Exception:  # pragma: no cover
    _HAS_SDK = False

_BUDGET_PATH = config.STATE_DIR / "call_budget.json"


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _budget_left():
    if config.DAILY_CALL_BUDGET <= 0:
        return True
    data = {}
    if _BUDGET_PATH.exists():
        try:
            data = json.loads(_BUDGET_PATH.read_text())
        except Exception:
            data = {}
    if data.get("date") != _today():
        return True
    return data.get("count", 0) < config.DAILY_CALL_BUDGET


def _budget_tick():
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    data = {}
    if _BUDGET_PATH.exists():
        try:
            data = json.loads(_BUDGET_PATH.read_text())
        except Exception:
            data = {}
    if data.get("date") != _today():
        data = {"date": _today(), "count": 0}
    data["count"] = data.get("count", 0) + 1
    _BUDGET_PATH.write_text(json.dumps(data))


class Brain:
    def __init__(self):
        backend = config.LLM_BACKEND
        self.omniroute = bool(config.OMNIROUTE_URL) and backend in (
            "auto", "omniroute")
        self._omni_ok = None  # lazy reachability probe cache
        self.gemini = (bool(config.GEMINI_API_KEY) and _HAS_SDK
                       and backend in ("auto", "gemini"))
        self._client = genai.Client(api_key=config.GEMINI_API_KEY) \
            if self.gemini else None
        self.online = self.omniroute or self.gemini

    # -- OmniRoute (OpenAI-compatible) -------------------------------------
    def _omni_reachable(self):
        if self._omni_ok is not None:
            return self._omni_ok
        try:
            req = urllib.request.Request(
                config.OMNIROUTE_URL.rstrip("/") + "/models",
                headers=self._omni_headers())
            urllib.request.urlopen(req, timeout=5).read()
            self._omni_ok = True
        except urllib.error.HTTPError:
            self._omni_ok = True
        except Exception:
            self._omni_ok = False
        return self._omni_ok

    @staticmethod
    def _omni_headers():
        h = {"Content-Type": "application/json"}
        if config.OMNIROUTE_API_KEY:
            h["Authorization"] = f"Bearer {config.OMNIROUTE_API_KEY}"
        return h

    def _omni_call(self, prompt, tries=3):
        url = config.OMNIROUTE_URL.rstrip("/") + "/chat/completions"
        body = json.dumps({
            "model": config.OMNIROUTE_MODEL,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        last = None
        for i in range(tries):
            try:
                req = urllib.request.Request(
                    url, data=body, headers=self._omni_headers(), method="POST")
                with urllib.request.urlopen(
                        req, timeout=config.OMNIROUTE_TIMEOUT) as resp:
                    data = json.loads(resp.read().decode())
                # OmniRoute is free/keyless — deliberately NOT counted against
                # the Gemini daily budget.
                return (data["choices"][0]["message"]["content"] or "").strip()
            except Exception as e:  # noqa
                last = e
                code = getattr(e, "code", None)
                if code in (429, 500, 502, 503, 504) or code is None:
                    time.sleep(min(2 ** i * 3, 30))
                    continue
                break
        raise last

    # -- Gemini SDK --------------------------------------------------------
    def _gemini_call(self, contents, tools=None, tries=4):
        cfg = types.GenerateContentConfig(tools=tools) if tools else None
        last = None
        for i in range(tries):
            try:
                r = self._client.models.generate_content(
                    model=config.GEMINI_MODEL, contents=contents, config=cfg)
                _budget_tick()
                return (r.text or "").strip()
            except Exception as e:  # noqa
                last = e
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "503" in msg:
                    time.sleep(min(2 ** i * 5, 40))
                    continue
                break
        raise last

    # -- public API --------------------------------------------------------
    def think(self, prompt, as_json=False):
        text = self._generate(prompt)
        if text is None:
            return self._offline(prompt, as_json)
        return self._extract_json(text) if as_json else text

    def research(self, query, as_json=False):
        """Live-internet research.

        Uses Gemini Google Search grounding only when Gemini is the serving
        backend (i.e. OmniRoute isn't available) — this avoids burning the
        Gemini free-tier quota on 429s while the router is handling traffic.
        Otherwise routes through OmniRoute (model knowledge). Always degrades
        gracefully to the offline stub.
        """
        omni_serving = self.omniroute and self._omni_reachable()
        if (self.gemini and not omni_serving
                and config.ENABLE_GROUNDING and _budget_left()):
            try:
                tool = types.Tool(google_search=types.GoogleSearch())
                text = self._gemini_call(query, tools=[tool])
                return self._extract_json(text) if as_json else text
            except Exception as e:
                print(f"[brain] grounding unavailable ({str(e)[:80]}); "
                      "falling back to router/model knowledge")
        return self.think(query, as_json=as_json)

    # -- backend cascade ---------------------------------------------------
    def _generate(self, prompt):
        """Return text from the first backend that answers, else None."""
        # OmniRoute first — free/keyless, not subject to the Gemini budget.
        if self.omniroute and self._omni_reachable():
            try:
                return self._omni_call(prompt)
            except Exception as e:
                print(f"[brain] omniroute failed ({str(e)[:100]}); "
                      "falling back")
        # Gemini only if the daily quota budget still allows it.
        if self.gemini and _budget_left():
            try:
                return self._gemini_call(prompt)
            except Exception as e:
                print(f"[brain] gemini failed ({str(e)[:100]}); "
                      "using offline fallback")
        return None

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _extract_json(text):
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
        for candidate in (text, _first_block(text)):
            if candidate is None:
                continue
            try:
                return json.loads(candidate.strip())
            except Exception:
                continue
        return {"raw": text}

    @staticmethod
    def _offline(prompt, as_json):
        if as_json:
            return {}
        return "[offline] no LLM backend available (router down, no key, or " \
               "budget exhausted)."


def _first_block(text):
    for open_c, close_c in (("{", "}"), ("[", "]")):
        i, j = text.find(open_c), text.rfind(close_c)
        if 0 <= i < j:
            return text[i:j + 1]
    return None
