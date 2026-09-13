"""Central configuration. All tunables live here."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
DOCS_DIR = ROOT / "docs"
POSTS_DIR = DOCS_DIR / "posts"

LEDGER_PATH = STATE_DIR / "ledger.json"
MEMORY_PATH = STATE_DIR / "memory.json"

# --- Brain -----------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Free-tier friendly model. Override with env if you like.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

# --- Economics (all USD) ---------------------------------------------------
# What the agent believes it costs to stay alive each run/month.
MONTHLY_FIXED_COST = float(os.environ.get("MONTHLY_FIXED_COST", "0.0"))
# Estimated cost per run (Gemini free tier ~= 0, but track anyway).
COST_PER_RUN = float(os.environ.get("COST_PER_RUN", "0.0"))
# If real balance dips below this, the agent enters "survival mode".
SURVIVAL_THRESHOLD = float(os.environ.get("SURVIVAL_THRESHOLD", "-5.0"))

# Affiliate / monetization config (wire to real values when ready).
AFFILIATE_TAG = os.environ.get("AFFILIATE_TAG", "")

# Blog identity
SITE_TITLE = os.environ.get("SITE_TITLE", "The Self-Funding Agent")
SITE_TAGLINE = os.environ.get(
    "SITE_TAGLINE", "An AI writing its way to paying its own bills."
)
