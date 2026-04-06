import os
import json
import httpx
from fastapi import APIRouter, Request, BackgroundTasks

from agent.orchestrator import handle_user_message
import config

router = APIRouter()

TELEGRAM_TOKEN = config.TELEGRAM_BOT_TOKEN
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
MAPPING_FILE = "telegram_users.json"

def get_mappings():
    if os.path.exists(MAPPING_FILE):
        with open(MAPPING_FILE, "r") as f:
            try:
                return json.load(f)
            except:
                return {}
    return {}

def save_mapping(chat_id: str, user_id: str):
    mappings = get_mappings()
    mappings[str(chat_id)] = user_id
    with open(MAPPING_FILE, "w") as f:
        json.dump(mappings, f)

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
                "parse_mode": "Markdown"
            }
        )

async def process_telegram_message(chat_id: int, text: str):
    chat_id_str = str(chat_id)
    mappings = get_mappings()
    
    # 1. Check for deep linking handshake token
    if text.startswith("/start "):
        user_id = text.split(" ")[1].strip()
        save_mapping(chat_id_str, user_id)
        await send_telegram_message(chat_id, "✅ Awesome! Your Telegram is now securely linked to your Zynd Agent. You can chat with me directly here! What would you like to do?")
        return

    # 2. Reject unauthenticated users
    if chat_id_str not in mappings:
        await send_telegram_message(chat_id, "⚠️ Your Telegram account is not linked to an active Persona. Please go to the Zynd Dashboard and click 'Connect Telegram'.")
        return

    user_id = mappings[chat_id_str]
    
    # 3. Handle basic commands
    if text == "/start":
        await send_telegram_message(chat_id, "Welcome back! What can I assist you with today?")
        return

    # 4. Orchestrate through the Agent System
    try:
        # Prefix conversation ID so telegram context isn't wiped by web context
        result = await handle_user_message(
            user_id=user_id,
            message=text,
            conversation_id=f"tg_{chat_id_str}"
        )
        reply = result.get("reply", "Done.")
        await send_telegram_message(chat_id, reply)
    except Exception as e:
         await send_telegram_message(chat_id, f"❌ Error processing request: {str(e)}")

@router.post("/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives incoming JSON payloads from Telegram servers in real-time.
    """
    try:
        data = await request.json()
    except Exception:
         return {"status": "ok"}
    
    # Extract message context safely
    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"]
        
        # We MUST process via background_tasks to immediately return a 200 OK to Telegram.
        # Otherwise, if the LLM takes > 5 seconds, Telegram assumes failure and spams the Webhook.
        background_tasks.add_task(process_telegram_message, chat_id, text)
        
    return {"status": "ok"}

@router.get("/register")
async def register_webhook():
    """
    Utility endpoint to officially set our backend URL with Telegram's servers.
    """
    if not TELEGRAM_TOKEN:
        return {"error": "TELEGRAM_BOT_TOKEN is missing from .env"}
        
    webhook_url = f"{config.ZYND_WEBHOOK_BASE_URL}/api/telegram/webhook"
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{TELEGRAM_API_URL}/setWebhook", json={"url": webhook_url})
        
    return resp.json()
