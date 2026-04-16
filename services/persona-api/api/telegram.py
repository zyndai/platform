"""
Telegram bot bridge.

Receives Telegram webhook events, maps chat_ids to Zynd users via the
telegram_links DB table (replacing the old telegram_users.json), and
routes messages through the orchestrator. Conversation history is
persisted per-chat in telegram_chat_history so the bot remembers prior
turns across backend restarts.

Handshake flow:
  1. User clicks "Connect Telegram" in the webapp → opens a deep link
     `https://t.me/<bot>?start=<supabase_user_id>`.
  2. Telegram opens the bot with `/start <supabase_user_id>`.
  3. We parse the token, persist the (user_id, chat_id) link row, and
     reply with a confirmation.

Memory flow:
  1. Load the persisted message list from telegram_chat_history into
     orchestrator._conversations[conv_id].
  2. Call handle_user_message — it appends the new turn to that list
     in place, exactly as it would for an ephemeral in-memory conv.
  3. Read the updated list back out of _conversations and upsert it
     to the DB so the next turn picks up the context.

v1 doesn't summarize or window the history — the full list is loaded
every turn. If context limits bite, we'll cap to the last N turns here.
"""

import httpx
from fastapi import APIRouter, Request, BackgroundTasks

from agent.orchestrator import handle_user_message, _conversations
from services import telegram_store
import config

router = APIRouter()

TELEGRAM_TOKEN = config.TELEGRAM_BOT_TOKEN
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


async def send_telegram_message(chat_id: int, text: str):
    if not TELEGRAM_TOKEN:
        print("[Telegram] Bot token not configured.")
        return

    async with httpx.AsyncClient() as client:
        await client.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            },
        )


def _conv_id_for(chat_id: str) -> str:
    """Conversation id namespace for Telegram chats — kept separate from
    the webapp's conversation ids so the two surfaces don't bleed into
    each other."""
    return f"tg_{chat_id}"


async def process_telegram_message(chat_id: int, text: str):
    chat_id_str = str(chat_id)

    # 1. Deep-linking handshake (/start <user_id>)
    if text.startswith("/start "):
        parts = text.split(" ", 1)
        user_id = parts[1].strip() if len(parts) > 1 else ""
        if not user_id:
            await send_telegram_message(chat_id, "⚠️ Missing link token. Please use the Connect Telegram button on your dashboard.")
            return
        telegram_store.link_chat_to_user(chat_id_str, user_id)
        await send_telegram_message(
            chat_id,
            "✅ Awesome! Your Telegram is now securely linked to your Zynd Agent. "
            "You can chat with me directly here! What would you like to do?",
        )
        return

    # 2. Reject unauthenticated chats
    user_id = telegram_store.get_user_id_for_chat(chat_id_str)
    if not user_id:
        await send_telegram_message(
            chat_id,
            "⚠️ Your Telegram account is not linked to an active Persona. "
            "Please go to the Zynd Dashboard and click 'Connect Telegram'.",
        )
        return

    # 3. Basic /start (no token) after link — friendly welcome
    if text.strip() == "/start":
        await send_telegram_message(chat_id, "Welcome back! What can I assist you with today?")
        return

    # 4. Optional /reset command to clear the chat history
    if text.strip() in ("/reset", "/clear"):
        telegram_store.clear_history(_conv_id_for(chat_id_str))
        _conversations.pop(_conv_id_for(chat_id_str), None)
        await send_telegram_message(chat_id, "🧹 Okay, I've forgotten our previous conversation. Fresh start!")
        return

    conv_id = _conv_id_for(chat_id_str)

    # 5. Orchestrate through the agent
    try:
        # Hydrate the orchestrator's in-memory history slot from the DB.
        # handle_user_message reads and appends to _conversations[conv_id];
        # we pre-fill it with the persisted turns so multi-turn context
        # survives backend restarts.
        _conversations[conv_id] = telegram_store.load_history(conv_id)

        result = await handle_user_message(
            user_id=user_id,
            message=text,
            conversation_id=conv_id,
        )
        reply = result.get("reply", "Done.")

        # Persist the updated history back to the DB.
        telegram_store.save_history(
            user_id=user_id,
            conversation_id=conv_id,
            messages=_conversations.get(conv_id, []),
        )

        await send_telegram_message(chat_id, reply)
    except Exception as e:
        await send_telegram_message(chat_id, f"❌ Error processing request: {str(e)}")


@router.post("/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives incoming JSON payloads from Telegram servers in real-time.
    Returns 200 OK immediately and processes in a background task —
    Telegram retries aggressively if the webhook takes >5s.
    """
    try:
        data = await request.json()
    except Exception:
        return {"status": "ok"}

    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"]
        background_tasks.add_task(process_telegram_message, chat_id, text)

    return {"status": "ok"}


@router.get("/register")
async def register_webhook():
    """One-shot helper to register our public webhook URL with Telegram."""
    if not TELEGRAM_TOKEN:
        return {"error": "TELEGRAM_BOT_TOKEN is missing from .env"}

    webhook_url = f"{config.ZYND_WEBHOOK_BASE_URL}/api/telegram/webhook"
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{TELEGRAM_API_URL}/setWebhook", json={"url": webhook_url})

    return resp.json()
