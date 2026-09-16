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
# Which LLM backend to prefer:
#   "auto"      -> try OmniRoute first (free multi-provider router), then
#                  fall back to the Gemini SDK, then offline stub.
#   "omniroute" -> OmniRoute only (never touches the Gemini quota).
#   "gemini"    -> Gemini SDK only (classic behaviour).
LLM_BACKEND = os.environ.get("LLM_BACKEND", "auto").lower()

# OmniRoute — local OpenAI-compatible router that aggregates many free-tier
# / keyless LLM providers with automatic fallback. Running it sidesteps the
# Gemini free-tier 429 quota entirely. Start it with `omniroute serve`.
OMNIROUTE_URL = os.environ.get("OMNIROUTE_URL", "http://localhost:20128/v1")
OMNIROUTE_MODEL = os.environ.get("OMNIROUTE_MODEL", "auto")
OMNIROUTE_API_KEY = os.environ.get("OMNIROUTE_API_KEY", "")
# Seconds to wait on an OmniRoute request (free providers can be slow).
OMNIROUTE_TIMEOUT = int(os.environ.get("OMNIROUTE_TIMEOUT", "90"))

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Free-tier friendly model. Override with env if you like.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
# Max live model calls per day (protects the free-tier quota; raise once
# API billing is enabled). 0 = unlimited.
DAILY_CALL_BUDGET = int(os.environ.get("DAILY_CALL_BUDGET", "40"))
# Whether to use Google Search grounding for research (needs quota/billing).
ENABLE_GROUNDING = os.environ.get("ENABLE_GROUNDING", "1") == "1"

# --- Research swarm --------------------------------------------------------
# Number of LOGICAL research workers to dispatch each night. These all run
# inside THIS one environment (a bounded thread pool) sharing the message bus
# — no extra accounts, no self-replication. Set 0 to use the single scout.
SWARM_WORKERS = int(os.environ.get("SWARM_WORKERS", "0"))
# How many workers may hit the LLM at once (protects the router / quota).
SWARM_CONCURRENCY = int(os.environ.get("SWARM_CONCURRENCY", "6"))
# Seconds before a single worker is abandoned (must exceed the LLM timeout
# below, or busy workers get killed mid-request under load).
SWARM_WORKER_TIMEOUT = int(os.environ.get("SWARM_WORKER_TIMEOUT", "150"))

# --- Economics (all USD) ---------------------------------------------------
# What the agent believes it costs to stay alive each run/month.
MONTHLY_FIXED_COST = float(os.environ.get("MONTHLY_FIXED_COST", "0.0"))
# Estimated cost per run (Gemini free tier ~= 0, but track anyway).
COST_PER_RUN = float(os.environ.get("COST_PER_RUN", "0.0"))
# If real balance dips below this, the agent enters "survival mode".
SURVIVAL_THRESHOLD = float(os.environ.get("SURVIVAL_THRESHOLD", "-5.0"))

# Affiliate / monetization config (wire to real values when ready).
AFFILIATE_TAG = os.environ.get("AFFILIATE_TAG", "")
AMAZON_DOMAIN = os.environ.get("AMAZON_DOMAIN", "www.amazon.in")

# --- Video backend ---------------------------------------------------------
# "builtin"     -> always-on $0 PIL renderer (agent/shorts.py). Works headless
#                  in CI with zero external deps. This is the guaranteed path.
# "openmontage" -> ALSO emit a rich render brief for the OpenMontage studio
#                  (Remotion + Piper TTS + open footage) to be produced on the
#                  operator's 24x7 machine, where an AI assistant drives its
#                  agentic pipeline. The builtin video is still produced so an
#                  unattended run never ends without a deliverable.
VIDEO_BACKEND = os.environ.get("VIDEO_BACKEND", "builtin").lower()
# Where the OpenMontage checkout lives (default: sibling of this repo).
OPENMONTAGE_DIR = os.environ.get(
    "OPENMONTAGE_DIR", str(ROOT.parent / "OpenMontage"))
# Render briefs the money agent hands off to OpenMontage are written here.
VIDEO_BRIEF_DIR = ROOT / "state" / "video_briefs"

# Public site location (used for canonical URLs, sitemap, RSS).
SITE_URL = os.environ.get("SITE_URL", "https://ddhabak1.github.io")
SITE_BASEURL = os.environ.get("SITE_BASEURL", "/self-funding-agent")

# Blog identity
SITE_TITLE = os.environ.get("SITE_TITLE", "The Self-Funding Agent")
SITE_TAGLINE = os.environ.get(
    "SITE_TAGLINE", "An AI writing its way to paying its own bills."
)

# --- Admin UI (agent/webui.py) ---------------------------------------------
# Human-in-the-loop control panel: shows the day's scouted top products, lets
# the operator paste their own approved affiliate link per product, and
# publishing kicks off content generation + marketing for exactly those.
#
# Default auth: a simple username/password form (change these via env vars —
# the defaults are meant to be overridden before exposing this publicly).
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123#")
# Optional upgrade: gate behind "Sign in with Google" instead, restricted to
# one account. Only used when both are set; falls back to username/password
# above otherwise.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
# Only this Google account may use the admin UI (single-operator tool).
ADMIN_ALLOWED_EMAIL = os.environ.get("ADMIN_ALLOWED_EMAIL", "")
# Signs the admin session cookie. If unset, a random one is generated and
# persisted to state/.session_secret so logins survive process restarts.
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")

# --- Autonomous social auto-posting (agent/distribute.py) -------------------
# Real accounts + official APIs, created ONCE by a human (required — no
# platform allows bot signups), then the agent posts on its own forever with
# zero further human input. Every block below no-ops safely when unset.
#
# X / Twitter — developer.twitter.com -> create a Project + App (free tier)
# -> Keys and tokens -> generate all four below (User authentication must be
# on, permissions = Read and Write).
TWITTER_API_KEY = os.environ.get("TWITTER_API_KEY", "")
TWITTER_API_SECRET = os.environ.get("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_SECRET = os.environ.get("TWITTER_ACCESS_SECRET", "")

# Reddit — reddit.com/prefs/apps -> create app, type "script" -> gives you
# the client id (under the app name) + secret. Uses your normal Reddit
# login (username/password) via Reddit's official OAuth2 script-app flow.
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USERNAME = os.environ.get("REDDIT_USERNAME", "")
REDDIT_PASSWORD = os.environ.get("REDDIT_PASSWORD", "")
# Subreddit to post value-first write-ups to (pick one that allows it).
REDDIT_SUBREDDIT = os.environ.get("REDDIT_SUBREDDIT", "")
REDDIT_USER_AGENT = os.environ.get(
    "REDDIT_USER_AGENT", "self-funding-agent/1.0 (by u/" +
    os.environ.get("REDDIT_USERNAME", "operator") + ")")

# Instagram — the most in-demand channel: convert to a Business/Creator
# account, link a Facebook Page, create a Meta Developer App, add the
# Instagram Graph API product, add yourself as an Instagram Tester (accept
# the invite in the Instagram app), then generate a long-lived access token
# with instagram_basic + instagram_content_publish + pages_show_list +
# pages_read_engagement. For single-account personal use like this, Meta's
# public App Review is NOT required — only the tester-approved account can
# be used, which is exactly what we want.
INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
# Your Instagram Business Account ID (from the Graph API, not the @handle).
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.environ.get(
    "INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
# Public base URL of THIS deployment (e.g. https://self-funding-agent.onrender.com)
# — Instagram's API fetches media by URL rather than accepting file uploads,
# so agent/server.py's /media/ route serves generated videos/images from here.
MEDIA_BASE_URL = os.environ.get("MEDIA_BASE_URL", "")
