import os
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

# ── Supabase / Postgres ──
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "http://127.0.0.1:54321")
SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
SUPABASE_JWT_SECRET: str = os.getenv("SUPABASE_JWT_SECRET", "")
# Postgres schema holding the cards tables and RPC functions. "public" on the
# dashboard project (xmfj) today; "cards" once cards runs on the shared aafo
# database (packages/db/cards). The schema must be listed in the project's
# API "Exposed schemas" setting.
SUPABASE_DB_SCHEMA: str = os.getenv("SUPABASE_DB_SCHEMA") or "public"

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

# Unowned cards published after claim tokens shipped can only be claimed with
# the one-time token returned at publish. Cards published before that have no
# token; set LEGACY_UNOWNED_CLAIM=true to let the first signed-in editor claim
# them (the old behaviour — lets any signed-in user take over such a card).
LEGACY_UNOWNED_CLAIM: bool = os.getenv("LEGACY_UNOWNED_CLAIM", "false").lower() in ("1", "true", "yes")

# ── LLM (OpenRouter) ──
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-pro")
OPENROUTER_REFERER: str = os.getenv("OPENROUTER_REFERER", "https://zynd.ai")
OPENROUTER_APP_NAME: str = os.getenv("OPENROUTER_APP_NAME", "zynd-cards")

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


def get_openai_client():
    from openai import OpenAI

    return OpenAI(api_key=OPENAI_API_KEY)
