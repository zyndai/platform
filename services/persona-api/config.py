"""
Zynd AI Networking Agent — Backend Configuration

Central config module.  Reads from .env and exposes typed settings
used by every other module so nothing is hard-coded elsewhere.
"""

# ── Prefer IPv4 for outbound DNS ────────────────────────────────────
# Python's getaddrinfo returns IPv6 records first when a host has both
# AAAA and A records. On boxes whose IPv6 path is broken (common with
# Cloudflare tunnels on residential networks), every fresh outbound
# connection hangs ~30s on the IPv6 TLS handshake before falling back.
# curl avoids this with Happy Eyeballs; Python doesn't. We install this
# patch at config-import time (every backend entrypoint imports config
# first) so every later HTTP/TLS call goes IPv4-first. Falls back to
# whatever DNS returned if no IPv4 record exists.
import socket as _socket
_orig_getaddrinfo = _socket.getaddrinfo
def _ipv4_first(host, *args, **kwargs):
    results = _orig_getaddrinfo(host, *args, **kwargs)
    v4 = [r for r in results if r[0] == _socket.AF_INET]
    return v4 or results
_socket.getaddrinfo = _ipv4_first  # type: ignore[assignment]

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the backend directory
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

# ── Supabase ─────────────────────────────────────────────────────────
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "http://127.0.0.1:54321")
SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")

# ── Twitter / X ──────────────────────────────────────────────────────
TWITTER_CLIENT_ID: str = os.getenv("TWITTER_CLIENT_ID", "")
TWITTER_CLIENT_SECRET: str = os.getenv("TWITTER_CLIENT_SECRET", "")
TWITTER_REDIRECT_URI: str = os.getenv(
    "TWITTER_REDIRECT_URI", "http://localhost:8000/api/oauth/twitter/callback"
)

# ── LinkedIn ─────────────────────────────────────────────────────────
LINKEDIN_CLIENT_ID: str = os.getenv("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET: str = os.getenv("LINKEDIN_CLIENT_SECRET", "")
LINKEDIN_REDIRECT_URI: str = os.getenv(
    "LINKEDIN_REDIRECT_URI", "http://localhost:8000/api/oauth/linkedin/callback"
)

# ── Google ───────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI: str = os.getenv(
    "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/oauth/google/callback"
)

# ── Notion ───────────────────────────────────────────────────────────
NOTION_CLIENT_ID: str = os.getenv("NOTION_CLIENT_ID", "")
NOTION_CLIENT_SECRET: str = os.getenv("NOTION_CLIENT_SECRET", "")
NOTION_REDIRECT_URI: str = os.getenv(
    "NOTION_REDIRECT_URI", "http://localhost:8000/api/oauth/notion/callback"
)

# ── Zynd AI (v2 — Ed25519/zns) ──────────────────────────────────────
# Path to the developer keypair JSON (created by `zynd init` / `zynd auth login`)
# This is the HD root from which all user persona keys are derived.
ZYND_DEVELOPER_KEYPAIR_PATH: str = os.getenv(
    "ZYND_DEVELOPER_KEYPAIR_PATH",
    os.path.expanduser("~/.zynd/developer.json")
)
ZYND_REGISTRY_URL: str = os.getenv("ZYND_REGISTRY_URL", "https://dns01.zynd.ai")
ZYND_WEBHOOK_BASE_URL: str = os.getenv("ZYND_WEBHOOK_BASE_URL", "")
NGROK_AUTH_TOKEN: str = os.getenv("NGROK_AUTH_TOKEN", "")

# ── Telegram ─────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ── OpenAI ───────────────────────────────────────────────────────────
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")

# ── Google Gemini ────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# ── Custom OpenAI-compatible endpoint ────────────────────────────────
# Use this for self-hosted models, LM Studio, Ollama, or any
# provider that exposes an OpenAI-compatible /v1/chat/completions API.
CUSTOM_LLM_BASE_URL: str = os.getenv("CUSTOM_LLM_BASE_URL", "")
CUSTOM_LLM_API_KEY: str = os.getenv("CUSTOM_LLM_API_KEY", "")
CUSTOM_LLM_MODEL: str = os.getenv("CUSTOM_LLM_MODEL", "")

# ── LLM Provider Selection ──────────────────────────────────────────
# "openai", "gemini", or "custom"
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")

# ── Apify (LinkedIn scraping) ────────────────────────────────────────
APIFY_API_TOKEN: str = os.getenv("APIFY_API_TOKEN", "")

# ── App ──────────────────────────────────────────────────────────────
APP_SECRET_KEY: str = os.getenv("APP_SECRET_KEY", "change-me-in-production")
FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")
