"""Central configuration for the marketing agent.

Everything lives in one Google ecosystem:
  - Gemini (text agents)        -> via Vertex AI
  - Gemini 2.5 Flash Image      -> branded post images
  - Firestore                   -> post queue, learned rules, prompt versions
  - Cloud Storage               -> hosted composited images
  - Cloud Run + Cloud Scheduler -> hosting + cron

The only justified externals are Telegram (mobile approval) and Buffer (publishing),
since those are the destinations, not "systems doing the job".

Make it your own: every brand- and domain-specific value below has a neutral
default and can be overridden via environment variables (see .env.example).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _env_list(name: str, default: str) -> list[str]:
    """Parse a comma-separated env var into a clean list of strings."""
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# ------------------------------------------------------------
# Google Cloud / Vertex AI
# ------------------------------------------------------------
GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
# ADK / google-genai read this to route through Vertex AI instead of the public API.
USE_VERTEX = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "TRUE").upper() == "TRUE"


# ------------------------------------------------------------
# Models — pick the cheapest model that does each job well.
#   Flash-Lite ($0.10/$0.40 per 1M) handles structured ranking/JSON.
#   Flash      ($0.30/$2.50 per 1M) handles nuanced brand copywriting + reflection.
#   Flash-Image ($0.039/img) bakes the headline into the visual (no separate compositor).
# ------------------------------------------------------------
MODEL_FAST = os.environ.get("MODEL_FAST", "gemini-2.5-flash-lite")
MODEL_SMART = os.environ.get("MODEL_SMART", "gemini-2.5-flash")
MODEL_IMAGE = os.environ.get("MODEL_IMAGE", "gemini-2.5-flash-image")


# ------------------------------------------------------------
# Firestore collections (single DB, replaces Supabase tables)
# ------------------------------------------------------------
COLLECTION_POSTS = "posts"
COLLECTION_TOPICS = "topics"
COLLECTION_REJECTIONS = "rejections"
COLLECTION_RULES = "learned_rules"          # Phase 3 self-learning output
COLLECTION_PROMPTS = "prompt_versions"      # Phase 3 prompt/context history
COLLECTION_CAMPAIGNS = "campaigns"          # Phase 2b campaign plans
COLLECTION_OUTCOMES = "publish_outcomes"    # Phase 2 monitor signal (fuel for reflector)

GCS_BUCKET = os.environ.get("GCS_BUCKET") or f"{GOOGLE_CLOUD_PROJECT}-post-images"

# Cloud Run service name (used by deploy scripts).
SERVICE_NAME = os.environ.get("SERVICE_NAME", "marketing-agent")


# ------------------------------------------------------------
# External destinations (Telegram = approval, Buffer = publishing)
# ------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

BUFFER_ACCESS_TOKEN = os.environ.get("BUFFER_ACCESS_TOKEN", "")
BUFFER_CHANNEL_IDS = {
    "instagram": os.environ.get("BUFFER_INSTAGRAM_CHANNEL_ID", ""),
    "pinterest": os.environ.get("BUFFER_PINTEREST_CHANNEL_ID", ""),
    "x": os.environ.get("BUFFER_X_CHANNEL_ID", ""),
}


# ------------------------------------------------------------
# Brand — override every value via env to make this package your own.
# ------------------------------------------------------------
BRAND_NAME = os.environ.get("BRAND_NAME", "Acme")
BRAND_TAGLINE = os.environ.get("BRAND_TAGLINE", "a product your audience loves")
BRAND_AUDIENCE = os.environ.get("BRAND_AUDIENCE", "your target audience")
# The subject area your content lives in (drives topic ranking + research).
BRAND_DOMAIN = os.environ.get("BRAND_DOMAIN", "your product's topic area")
BRAND_COLORS = os.environ.get(
    "BRAND_COLORS", "clean neutral palette with a single accent color"
)
BRAND_VOICE = os.environ.get(
    "BRAND_VOICE", "clear, helpful, on-brand — never salesy or preachy"
)
# Criteria used to rank candidate topics, most important first.
RANKING_CRITERIA = _env_list(
    "RANKING_CRITERIA",
    "relevance to the brand,emotional resonance with the audience,shareability",
)

PLATFORMS = tuple(_env_list("PLATFORMS", "instagram,pinterest,x"))

# How many topics -> posts per day. 3 topics x N platforms.
TOPICS_PER_DAY = int(os.environ.get("TOPICS_PER_DAY", "3"))

# Which provider supplies trend signals: "rss", "vectordb", "none", or a
# dotted path "module:Class" pointing at your own SourceProvider implementation.
SOURCE_PROVIDER = os.environ.get("SOURCE_PROVIDER", "rss")

# Content source feeds (used by the RSS provider). RSS is robust: no auth, no
# 403s. Override with your own comma-separated feed URLs.
SOURCE_FEEDS = _env_list("SOURCE_FEEDS", "https://www.theguardian.com/world/rss")

# Publishing slots (local hour). Approved posts fill the next open slot.
PUBLISH_SLOTS = (9, 12, 15, 18, 21)
LOCAL_TZ = os.environ.get("LOCAL_TZ", "UTC")


# ------------------------------------------------------------
# Optional VectorDB source provider (Postgres + pgvector).
# Only used when SOURCE_PROVIDER=vectordb. Bring your own knowledge base:
# point these at any table with a text payload and a pgvector embedding column.
# ------------------------------------------------------------
WARDROBE_DB_CONNECTION_NAME = os.environ.get("WARDROBE_DB_CONNECTION_NAME", "")
WARDROBE_DB_NAME = os.environ.get("WARDROBE_DB_NAME", "")
WARDROBE_DB_USER = os.environ.get("WARDROBE_DB_USER", "postgres")
WARDROBE_DB_PASSWORD = os.environ.get("WARDROBE_DB_PASSWORD", "")
WARDROBE_DB_USE_IAM = os.environ.get("WARDROBE_DB_USE_IAM", "FALSE").upper() == "TRUE"
WARDROBE_DB_PRIVATE_IP = os.environ.get("WARDROBE_DB_PRIVATE_IP", "FALSE").upper() == "TRUE"
WARDROBE_DB_TABLE = os.environ.get("WARDROBE_DB_TABLE", "knowledge_base")
WARDROBE_DB_EMBED_COLUMN = os.environ.get("WARDROBE_DB_EMBED_COLUMN", "embedding")
WARDROBE_DB_TEXT_COLUMNS = _env_list("WARDROBE_DB_TEXT_COLUMNS", "title,body")
WARDROBE_TOP_K = int(os.environ.get("WARDROBE_TOP_K", "12"))
WARDROBE_EMBED_PROVIDER = os.environ.get("WARDROBE_EMBED_PROVIDER", "openai")
WARDROBE_EMBED_MODEL = os.environ.get("WARDROBE_EMBED_MODEL", "text-embedding-3-small")
WARDROBE_EMBED_DIM = int(os.environ.get("WARDROBE_EMBED_DIM", "1536"))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")


# ------------------------------------------------------------
# Phase 2 — Pipeline mode
#   "department" = the Phase 2 multi-agent department (research -> campaign ->
#                  per-post critic loop -> guardrail gate)
#   "phase1"     = the original linear SequentialAgent baseline (pipeline.py)
# ------------------------------------------------------------
PIPELINE_MODE = os.environ.get("PIPELINE_MODE", "department")


# ------------------------------------------------------------
# Phase 2 — Critic loop (evaluator-optimizer) bounds
# ------------------------------------------------------------
CRITIC_MAX_ITERATIONS = int(os.environ.get("CRITIC_MAX_ITERATIONS", "3"))
CRITIC_PASS_SCORE = int(os.environ.get("CRITIC_PASS_SCORE", "4"))  # 1-5 scale


# ------------------------------------------------------------
# Phase 2c — Regional intelligence (injected into content prompts)
# ------------------------------------------------------------
REGION = os.environ.get("REGION", "Global")
LOCALE = os.environ.get("LOCALE", "en")
# Hemisphere drives season inference (summer/winter flip across the equator).
HEMISPHERE = os.environ.get("HEMISPHERE", "northern")
# Notable cultural moments to be aware of (kept short; the brief agent decides
# whether any are timely). Override per market via env as a comma-separated list.
REGIONAL_HOLIDAYS = _env_list("REGIONAL_HOLIDAYS", "")
CULTURAL_SENSITIVITIES = os.environ.get(
    "CULTURAL_SENSITIVITIES",
    "Be inclusive across cultures, faiths, and regions; avoid stereotypes and "
    "judgments about appearance; respect local norms and seasonal realities.",
)


# ------------------------------------------------------------
# Phase 2b — Per-platform "fit" guidance (campaign + content agents read this)
# ------------------------------------------------------------
PLATFORM_FIT = {
    "instagram": {
        "best_for": "visual style inspiration, carousels-feeling single cards, saves",
        "caption_len": "<=125 chars before the fold",
        "max_hashtags": 12,
    },
    "pinterest": {
        "best_for": "evergreen how-to / keyword-rich discovery",
        "caption_len": "title <=100 chars + SEO description 200-300 chars",
        "max_hashtags": 6,
    },
    "x": {
        "best_for": "punchy opinion / quick tips, conversation",
        "caption_len": "<=240 chars",
        "max_hashtags": 2,
    },
}


# ------------------------------------------------------------
# Phase 2b — Anti-spam guardrail thresholds
# ------------------------------------------------------------
# Words/phrases that trip platform spam filters or read as cheap marketing.
SPAM_TRIGGER_WORDS = [
    "buy now", "click here", "link in bio now", "limited time", "act now",
    "100% free", "guaranteed", "dm me", "follow for follow", "f4f",
    "free money", "earn cash", "subscribe now", "discount code",
]
# How similar a new caption may be to a recent one (0-1, SequenceMatcher ratio).
DUPLICATE_SIMILARITY_THRESHOLD = float(
    os.environ.get("DUPLICATE_SIMILARITY_THRESHOLD", "0.82")
)
# How many recent posts to compare against for near-duplicate detection.
DEDUP_LOOKBACK = int(os.environ.get("DEDUP_LOOKBACK", "40"))
# Max distinct CTAs / links a single caption should contain.
MAX_LINKS_PER_CAPTION = int(os.environ.get("MAX_LINKS_PER_CAPTION", "1"))


# ------------------------------------------------------------
# Phase 2 — Durable publish retry (Performance Monitor)
#   On a failed publish we DON'T sleep (Cloud Run scales to zero). We persist a
#   retry_at timestamp and a 5-min Cloud Scheduler poll re-attempts once.
# ------------------------------------------------------------
RETRY_DELAY_MINUTES = int(os.environ.get("RETRY_DELAY_MINUTES", "15"))
MAX_PUBLISH_RETRIES = int(os.environ.get("MAX_PUBLISH_RETRIES", "1"))
