"""
Register the bot's webhook URL with Telegram, including the secret token that
Telegram echoes back on every update as X-Telegram-Bot-Api-Secret-Token.

Replaces the old public GET /api/telegram/register route. Run on PROD only —
a bot has exactly one webhook URL, so running this from dev steals prod's
traffic.

    cd backend
    python scripts/register_telegram_webhook.py            # register
    python scripts/register_telegram_webhook.py --info     # show current webhook

Requires TELEGRAM_BOT_TOKEN, ZYND_WEBHOOK_BASE_URL and TELEGRAM_WEBHOOK_SECRET
in backend/.env. Generate a secret with:

    python -c "import secrets; print(secrets.token_urlsafe(32))"

Rollout order: deploy the backend with TELEGRAM_WEBHOOK_SECRET set, then run
this script — updates are rejected (401) until Telegram knows the secret.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--info", action="store_true", help="print the current webhook info and exit")
    args = parser.parse_args()

    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        print("TELEGRAM_BOT_TOKEN is missing from backend/.env", file=sys.stderr)
        return 1
    api = f"https://api.telegram.org/bot{token}"

    if args.info:
        print(httpx.get(f"{api}/getWebhookInfo", timeout=15).json())
        return 0

    base = config.ZYND_WEBHOOK_BASE_URL.rstrip("/")
    secret = config.TELEGRAM_WEBHOOK_SECRET
    if not base or not secret:
        print("ZYND_WEBHOOK_BASE_URL and TELEGRAM_WEBHOOK_SECRET must both be set", file=sys.stderr)
        return 1

    resp = httpx.post(
        f"{api}/setWebhook",
        json={"url": f"{base}/api/telegram/webhook", "secret_token": secret},
        timeout=15,
    )
    body = resp.json()
    print(body)
    return 0 if body.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
