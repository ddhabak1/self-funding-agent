"""The 'brain' — wraps the Gemini API (free tier) with graceful fallback."""
import json

from . import config

try:
    from google import genai  # google-genai SDK
    _HAS_SDK = True
except Exception:  # pragma: no cover
    _HAS_SDK = False


class Brain:
    def __init__(self):
        self.online = bool(config.GEMINI_API_KEY) and _HAS_SDK
        self._client = None
        if self.online:
            self._client = genai.Client(api_key=config.GEMINI_API_KEY)

    def think(self, prompt, as_json=False):
        """Return model text, or a safe offline stub if no key is set."""
        if not self.online:
            return self._offline(prompt, as_json)
        resp = self._client.models.generate_content(
            model=config.GEMINI_MODEL, contents=prompt
        )
        text = (resp.text or "").strip()
        if as_json:
            return self._extract_json(text)
        return text

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _extract_json(text):
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
        try:
            return json.loads(text.strip())
        except Exception:
            return {"raw": text}

    @staticmethod
    def _offline(prompt, as_json):
        if as_json:
            return {
                "title": "Placeholder Post (set GEMINI_API_KEY to go live)",
                "slug": "placeholder-post",
                "tags": ["setup"],
                "body": "This is an offline stub. Add a Gemini API key so the "
                "agent can actually write.",
            }
        return "[offline] Set GEMINI_API_KEY to enable real reasoning."
