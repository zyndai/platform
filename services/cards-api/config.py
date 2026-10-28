import os
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

# ── Supabase / Postgres ──
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "http://127.0.0.1:54321")
SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
SUPABASE_JWT_SECRET: str = os.getenv("SUPABASE_JWT_SECRET", "")
# Postgres schema holding the cards tables and RPC functions. Defaults to the
# shared cards schema; legacy databases can explicitly set "public". The schema
# needs its migrations and must be listed in the API "Exposed schemas" setting.
SUPABASE_DB_SCHEMA: str = os.getenv("SUPABASE_DB_SCHEMA") or "cards"

# Supabase project(s) whose tokens cards-api trusts for auth (not DB access —
# SUPABASE_URL above is still the only project queried). Comma-separated
# project base URLs; defaults to just SUPABASE_URL so single-project deploys
# need no new config. During the aafo migration this holds both xmfj and aafo.
TRUSTED_SUPABASE_URLS: list[str] = [
    u.strip() for u in os.getenv("TRUSTED_SUPABASE_URLS", "").split(",") if u.strip()
] or [SUPABASE_URL]

# aafo's issuer — the one project whose `sub` claim is a real auth.users id
# that the cards.agent_profile_cards.owner_user_id FK can reference. xmfj's
# `sub` values don't exist in aafo's auth.users, so they're never stamped.
AAFO_ISSUER: str = os.getenv("AAFO_ISSUER", "")

# Blocks writes during the aafo data cutover window (Phase G/H of the DB
# unify plan). POST/PATCH/PUT/DELETE return 503; reads keep working.
MAINTENANCE_READONLY: bool = os.getenv("MAINTENANCE_READONLY", "false").lower() in ("1", "true", "yes")

# owner_user_id exists only on aafo (cards.agent_profile_cards), not on xmfj's
# public.agent_profile_cards. Until the cutover switches SUPABASE_DB_SCHEMA to
# "cards", never send it: PostgREST rejects writes naming an unknown column.
# Cards written before then get owner_user_id from the cutover backfill (by email).
WRITES_OWNER_USER_ID: bool = SUPABASE_DB_SCHEMA == "cards"
FEATURE_S12_INTROS: bool = os.getenv("FEATURE_S12_INTROS", "false").lower() in ("1", "true", "yes")
# A2: invite someone who has no claimed Card yet. Creates an unclaimed Card about a third party
# from public LinkedIn data and needs cards.connection_invites (packages/db 0024). Off by default.
# Saved searches, reports, blocks, match preferences, request limits and verification badges
# (A3, A6, A8). They need packages/db migration 0025 (cards.saved_searches, card_reports,
# card_verifications, match_preferences). Off by default.
FEATURE_NETWORK_CONTROLS: bool = os.getenv("FEATURE_NETWORK_CONTROLS", "false").lower() in ("1", "true", "yes")
FEATURE_A2_INVITE_TO_CLAIM: bool = os.getenv("FEATURE_A2_INVITE_TO_CLAIM", "false").lower() in ("1", "true", "yes")
# Group memory + Card assistant replies (packages/db cards 0026). Both stay
# off until the migration is applied and the dev flow is verified.
FEATURE_GROUP_MEMORY: bool = os.getenv("FEATURE_GROUP_MEMORY", "false").lower() in ("1", "true", "yes")
FEATURE_GROUP_AGENT_REPLIES: bool = os.getenv("FEATURE_GROUP_AGENT_REPLIES", "true").lower() in ("1", "true", "yes")
GROUP_MEMORY_SUMMARY_EVERY: int = int(os.getenv("GROUP_MEMORY_SUMMARY_EVERY", "30"))
GROUP_MEMORY_RECENT_MESSAGES: int = int(os.getenv("GROUP_MEMORY_RECENT_MESSAGES", "50"))
GROUP_MEMORY_SEARCH_LIMIT: int = int(os.getenv("GROUP_MEMORY_SEARCH_LIMIT", "8"))
GROUP_AGENT_POLL_SECONDS: float = float(os.getenv("GROUP_AGENT_POLL_SECONDS", "2"))
GROUP_AGENT_MAX_STEPS: int = int(os.getenv("GROUP_AGENT_MAX_STEPS", "4"))
# Reply budget. Short chat replies stay the default; this is the ceiling for a
# plan / comparison / detailed answer. The reply cap must not exceed what
# cards.network_send_agent_group_message stores: 4000 until packages/db cards
# 0028 is applied, 8000 after. Raise it only once the migration is live.
GROUP_AGENT_MAX_TOKENS: int = int(os.getenv("GROUP_AGENT_MAX_TOKENS", "1800"))
GROUP_AGENT_MAX_REPLY_CHARS: int = int(os.getenv("GROUP_AGENT_MAX_REPLY_CHARS", "4000"))
# Per model call. A long answer at ~40 tokens/s takes about a minute.
GROUP_AGENT_LLM_TIMEOUT: float = float(os.getenv("GROUP_AGENT_LLM_TIMEOUT", "120"))
# Stream the reply to the group as it is written (Supabase Realtime REST
# broadcast, event "agent_stream"). Best effort: the durable message is still
# written once at the end. A no-op without SUPABASE_URL + SUPABASE_SERVICE_KEY.
FEATURE_GROUP_AGENT_STREAMING: bool = os.getenv("FEATURE_GROUP_AGENT_STREAMING", "true").lower() in ("1", "true", "yes")
# Dev only. Adds the context the assistant was given and every tool call it
# made to agent_stream payloads, which every member of the group receives.
# Never enable in production. Nothing is stored.
FEATURE_AGENT_DEBUG_SOURCES: bool = os.getenv("FEATURE_AGENT_DEBUG_SOURCES", "false").lower() in ("1", "true", "yes")
PERSONA_API_URL: str = os.getenv("PERSONA_API_URL", "http://127.0.0.1:8000")
PERSONA_SITE_URL: str = os.getenv("PERSONA_SITE_URL", "https://persona.zynd.ai")
CARDS_INTRO_SERVICE_TOKEN: str = os.getenv("CARDS_INTRO_SERVICE_TOKEN", "")

# Unowned cards published after claim tokens shipped can only be claimed with
# the one-time token returned at publish. Cards published before that have no
# token; set LEGACY_UNOWNED_CLAIM=true to let the first signed-in editor claim
# them (the old behaviour — lets any signed-in user take over such a card).
LEGACY_UNOWNED_CLAIM: bool = os.getenv("LEGACY_UNOWNED_CLAIM", "false").lower() in ("1", "true", "yes")

# S03: unclaimed cards are public to people but quiet to agents. When on,
# agent endpoints (/ask, /v1/agents/search) exclude unclaimed cards unless the
# caller passes include_unclaimed=true (the website's own UI does). Rollback:
# set to "false" and the old include-everyone behaviour returns.
FEATURE_S03_UNCLAIMED_TIERING: bool = os.getenv("FEATURE_S03_UNCLAIMED_TIERING", "true").lower() in ("1", "true", "yes")

# S04: enabled by default; requires migration 0008 on the cards schema.
# Set FEATURE_S04_EVENTS=false to disable collection explicitly.
FEATURE_S04_EVENTS: bool = os.getenv("FEATURE_S04_EVENTS", "true").lower() in ("1", "true", "yes")

# S06: typed memory match_reasons + freshness boost on /ask. Chat always
# uses CardView (see api/chat.py). /view + memory-in-embed stay always on.
# Rollback the search boost: set false.
FEATURE_S06_CARDVIEW: bool = os.getenv("FEATURE_S06_CARDVIEW", "true").lower() in ("1", "true", "yes")

# S08: onboarding v2 (live preview, no quiz). UX gate lives in cards-web
# (NEXT_PUBLIC_FEATURE_S08_* + zynd_s08 cookie). This mirrors ops visibility.
FEATURE_S08_ONBOARDING_V2: bool = os.getenv("FEATURE_S08_ONBOARDING_V2", "false").lower() in ("1", "true", "yes")
# Optional fixed prefix for the daily-rotating IP salt. Empty = derive from
# SUPABASE_JWT_SECRET + UTC date.
EVENTS_IP_SALT: str = os.getenv("EVENTS_IP_SALT", "")
# Shared secret our own servers (cards-web's server-side agent-fetch log, Memory's MCP reads)
# send as X-Zynd-Server-Event on POST /events. Only batches carrying it can trigger an AI-read
# alert email: the endpoint is public and actor_class comes from a User-Agent anyone can set.
# Empty = nothing is trusted, so no alert is ever sent from POST /events.
EVENTS_SERVER_TOKEN: str = os.getenv("EVENTS_SERVER_TOKEN", "")

# S03 "Not me" takedown: when a visitor reports a scraped card isn't theirs,
# cards-api posts the request to the shared Mattermost incoming webhook so a
# human can review the queue manually (same webhook URL as the deploy-failure
# alert in infra). Empty = no notification (the queue still fills).
MATTERMOST_WEBHOOK_URL: str = os.getenv("MATTERMOST_WEBHOOK_URL", "")

# cards-web cache bust after a memory snapshot write. The URL is a fixed
# constant in prod (the cards-web /api/revalidate route); the env var only
# exists to override it in local dev (e.g. http://localhost:3002/api/revalidate).
# The secret must be set to the same value in cards-web; unset = no-op.
WEB_REVALIDATE_URL: str = os.getenv(
    "WEB_REVALIDATE_URL", "https://cards.zynd.ai/api/revalidate"
)
WEB_REVALIDATE_SECRET: str = os.getenv("WEB_REVALIDATE_SECRET", "")

# ── LLM (OpenRouter) ──
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-pro")
OPENROUTER_REFERER: str = os.getenv("OPENROUTER_REFERER", "https://zynd.ai")
OPENROUTER_APP_NAME: str = os.getenv("OPENROUTER_APP_NAME", "zynd-cards")

# AI visibility report (POST /cards/visibility/check): what a web-searching model says about a
# name today. Off = the endpoint 404s. The model must search the web itself, so it is separate
# from OPENROUTER_MODEL. perplexity/sonar on OpenRouter (checked 2026-10-28): $1/M tokens in and
# out plus $0.005 per request for search, about $0.006 per uncached check.
FEATURE_AI_VISIBILITY: bool = os.getenv("FEATURE_AI_VISIBILITY", "false").lower() in ("1", "true", "yes")
AI_VISIBILITY_MODEL: str = os.getenv("AI_VISIBILITY_MODEL", "perplexity/sonar")
# Shown to the visitor under the answer ("Answer from <label> via API").
AI_VISIBILITY_MODEL_LABEL: str = os.getenv("AI_VISIBILITY_MODEL_LABEL", "Perplexity Sonar")
# Paid model calls per UTC day across every visitor (services/visibility.py), so many addresses
# cannot add up to an unbounded bill. 300 is about $1.80 a day at the price above.
AI_VISIBILITY_DAILY_CAP: int = max(0, int(os.getenv("AI_VISIBILITY_DAILY_CAP", "300")))

# ── OpenAI (embeddings) ──
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

# ── X / Twitter bot ──
X_API_KEY: str = os.getenv("X_API_KEY", "")            # Consumer Key (OAuth 1.0a, still needed for some endpoints)
X_API_SECRET: str = os.getenv("X_API_SECRET", "")      # Consumer Secret
X_BEARER_TOKEN: str = os.getenv("X_BEARER_TOKEN", "")  # App-only reads (search mentions)
# OAuth 2.0 user context — used for posting replies as the bot account
X_USER_ACCESS_TOKEN: str = os.getenv("X_USER_ACCESS_TOKEN", "")
X_USER_REFRESH_TOKEN: str = os.getenv("X_USER_REFRESH_TOKEN", "")
X_CLIENT_ID: str = os.getenv("X_CLIENT_ID", "")
X_CLIENT_SECRET: str = os.getenv("X_CLIENT_SECRET", "")
X_BOT_HANDLE: str = os.getenv("X_BOT_HANDLE", "ZyndAI")

# ── Scraping ──
GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
APIFY_API_KEY: str = os.getenv("APIFY_API_KEY", "")

# Shared with cards-web's image proxy: authorizes the avatar self-heal trigger
# (/cards/internal/refresh-avatar/{handle}) that fires when a stored LinkedIn
# avatar URL starts failing. Set to the same value in both services.
AVATAR_REFRESH_TOKEN: str = os.getenv("AVATAR_REFRESH_TOKEN", "")

# ── Cloudflare Workers AI (profile chatbot) ──
CLOUDFLARE_ACCOUNT_ID: str = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_AI_KEY: str = os.getenv("CLOUDFLARE_AI_KEY", "")
CLOUDFLARE_AI_MODEL: str = "@cf/meta/llama-3.1-8b-instruct-fast"

# ── Site / indexing ──
SITE_BASE_URL: str = os.getenv("SITE_BASE_URL", "https://zynd.ai")
API_BASE_URL: str = os.getenv("API_BASE_URL", "https://api.zynd.ai")
FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")
INDEXNOW_KEY: str = os.getenv("INDEXNOW_KEY", "")
BING_API_KEY: str = os.getenv("BING_API_KEY", "")
BING_SITE_URL: str = os.getenv("BING_SITE_URL", "https://zynd.ai")

# ── ZYND memory layer (cron refresh of public findability facts) ──
MEMORY_LAYER_URL: str = os.getenv("MEMORY_LAYER_URL", "https://api.zynd.ai")
MEMORY_SERVICE_TOKEN: str = os.getenv("MEMORY_SERVICE_TOKEN", "")
MEMORY_REFRESH_INTERVAL_HOURS: int = int(os.getenv("MEMORY_REFRESH_INTERVAL_HOURS", "6"))

# ── QuickEnrich (free contact-finder only; cards-api owns this client) ──
# QuickEnrich lives in Memory now (POST /v1/service/outside-people), the only client. These four
# are unused here and kept only so existing env files stay valid; only QUICKENRICH_TIMEOUT is read.
QUICKENRICH_BASE_URL: str = os.getenv("QUICKENRICH_BASE_URL", "")
QUICKENRICH_API_KEY: str = os.getenv("QUICKENRICH_API_KEY", "")
QUICKENRICH_AUTH_HEADER: str = os.getenv("QUICKENRICH_AUTH_HEADER", "Authorization")
QUICKENRICH_TIMEOUT: float = float(os.getenv("QUICKENRICH_TIMEOUT", "30"))

# ── Morning digest (SMTP + GitHub Actions cron) ──
SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM: str = os.getenv("SMTP_FROM", "")
CRON_SECRET: str = os.getenv("CRON_SECRET", "")
# The digest goes out at 07:00 in each owner's stored timezone. Owners without one (haven't
# opened /home since it started recording it) get 07:00 here, which is what everyone got
# when the digest was a single fixed-time run.
DIGEST_DEFAULT_TIMEZONE: str = os.getenv("DIGEST_DEFAULT_TIMEZONE") or "Asia/Kolkata"

# S10: enabled by default; requires migrations 0010/0011 on the cards schema.
# Set FEATURE_S10_HOME=false to disable owner-home operations explicitly.
FEATURE_S10_HOME: bool = os.getenv("FEATURE_S10_HOME", "true").lower() in ("1", "true", "yes")
FEATURE_S10_DIGEST: bool = os.getenv("FEATURE_S10_DIGEST", "false").lower() in ("1", "true", "yes")
S10_MAILER: str = os.getenv("S10_MAILER", "noop")  # noop | smtp

# Email a claimed card's owner as soon as an AI agent reads the card (services/ai_read_alerts.py).
# Sends through S10_MAILER, so nothing goes out unless that is "smtp" too. Off by default.
FEATURE_AI_READ_ALERTS: bool = os.getenv("FEATURE_AI_READ_ALERTS", "false").lower() in ("1", "true", "yes")
# At most one alert per card in this many hours. Floored at 1: a 0 here would email the owner
# on every crawler hit.
AI_READ_ALERT_COOLDOWN_HOURS: int = max(1, int(os.getenv("AI_READ_ALERT_COOLDOWN_HOURS", "24")))

# Dim a card's "Working on" chips, offer the owner a "Still working on this?" confirm, and add a
# nudge line to the morning digest once Working on has not changed for STALE_DAYS
# (services/stale_signals.py). Off by default. Needs packages/db cards migration 0033 for the
# timestamp; without it every card reads as "unknown" (never stale) and confirm answers 503.
FEATURE_STALE_SIGNALS: bool = os.getenv("FEATURE_STALE_SIGNALS", "false").lower() in ("1", "true", "yes")


def _get_supabase():
    global _sb_service
    if _sb_service is None:
        from supabase import ClientOptions, create_client

        _sb_service = create_client(
            SUPABASE_URL,
            SUPABASE_SERVICE_KEY,
            options=ClientOptions(schema=SUPABASE_DB_SCHEMA),
        )
    return _sb_service


_sb_service = None


def get_supabase():
    return _get_supabase()


def get_llm_client():
    from openai import OpenAI

    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
        default_headers={
            "HTTP-Referer": OPENROUTER_REFERER,
            "X-Title": OPENROUTER_APP_NAME,
        },
    )


_openai_client = None


def get_openai_client():
    """One client for the process: a new one per call paid a fresh TLS handshake on every search."""
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI

        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client
