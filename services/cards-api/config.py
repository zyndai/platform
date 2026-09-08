import os
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

# ── Supabase / Postgres ──
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "http://127.0.0.1:54321")
SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")

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


def _get_supabase():
    global _sb_service
    if _sb_service is None:
        from supabase import create_client

        _sb_service = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
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
