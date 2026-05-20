#!/usr/bin/env bash
#
# Re-register the @zynd_brief_bot command menu with BotFather.
# Run this after deploys that add/remove/rename slash commands so
# Telegram's "/" picker stays in sync with what the backend supports.
#
# Requires TELEGRAM_BOT_TOKEN in the environment (the same value used by
# the backend's .env). Idempotent — re-run anytime.

set -euo pipefail

TOKEN="${TELEGRAM_BOT_TOKEN:-}"
if [[ -z "$TOKEN" ]]; then
  echo "TELEGRAM_BOT_TOKEN is unset. Export it before running this script." >&2
  exit 1
fi

curl -sS -X POST "https://api.telegram.org/bot${TOKEN}/setMyCommands" \
  -H "Content-Type: application/json" \
  -d '{"commands":[
    {"command":"brief","description":"Show your current brief"},
    {"command":"brief_add","description":"Append a line to your brief"},
    {"command":"brief_replace","description":"Replace your entire brief"},
    {"command":"brief_clear","description":"Empty your brief"},
    {"command":"meetings","description":"Pending meeting tickets"},
    {"command":"calendar","description":"Today or this week — /calendar today|week"},
    {"command":"inbox","description":"Recent agent-channel messages awaiting a reply"},
    {"command":"who","description":"Find a persona — /who <name>"},
    {"command":"connect","description":"Send a connection request — /connect <handle>"},
    {"command":"connections","description":"Your network connections"},
    {"command":"todos","description":"Your open todos"},
    {"command":"todo","description":"Add a todo — /todo <text>"},
    {"command":"reset","description":"Forget our chat history"},
    {"command":"help","description":"Show command list"}
  ]}'
echo
