from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import time
import requests

import config
from supabase import create_client
from zyndai_agent.config_manager import ConfigManager
from zyndai_agent.message import AgentMessage
from agent.orchestrator import handle_user_message

router = APIRouter()

# ── Models ──────────────────────────────────────────────────────────

class PersonaRegisterRequest(BaseModel):
    user_id: str
    name: str
    description: str
    capabilities: List[str]
    price: Optional[str] = "Free"

class SyncWebhookResponse(BaseModel):
    status: str
    message_id: str
    response: Any
    timestamp: float

# ── Network Registration ─────────────────────────────────────────────

@router.get("/{user_id}/status")
async def get_persona_status(user_id: str):
    """Check if the user has already provisioned a persona on the network."""
    config_dir = f".agent-{user_id}"
    agent_config = ConfigManager.load_config(config_dir)
    if not agent_config:
        return {"deployed": False}
        
    webhook_base = config.ZYND_WEBHOOK_BASE_URL or ""
    return {
        "deployed": True,
        "name": agent_config.get("name"),
        "did": agent_config.get("didIdentifier"),
        "webhook_url": f"{webhook_base.rstrip('/')}/api/webhooks/{user_id}"
    }


@router.post("/register")
async def register_persona(req: PersonaRegisterRequest):
    """
    Register a user as a standard discoverable Agent on the Zynd AI Network.
    This provisions a DID (if none exists) and updates the webhook pointer
    so other agents can reach this user's persona via this application.
    """
    if not config.ZYND_API_KEY:
        raise HTTPException(status_code=500, detail="ZYND_API_KEY is not configured.")

    webhook_base = config.ZYND_WEBHOOK_BASE_URL
    if not webhook_base:
        raise HTTPException(status_code=500, detail="ZYND_WEBHOOK_BASE_URL is not configured. Start the server with Ngrok or set the environment variable.")

    # 1. Provision or load Identity via SDK's ConfigManager
    config_dir = f".agent-{req.user_id}"
    
    # We parse the capabilities string list into the expected dict structure
    # E.g. {"ai": req.capabilities, "protocols": ["http"], "services": ["persona"]}
    capabilities_dict = {
        "ai": req.capabilities,
        "protocols": ["http"],
        "services": ["persona"]
    }
    
    agent_config = ConfigManager.load_config(config_dir)
    if not agent_config:
        try:
            agent_config = ConfigManager.create_agent(
                registry_url=config.ZYND_REGISTRY_URL,
                api_key=config.ZYND_API_KEY,
                name=req.name,
                description=req.description,
                capabilities=capabilities_dict,
                config_dir=config_dir
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # 2. Update webhook pointer in Zynd Registry
    # This ensures that searches on the Zynd Network point to our global router
    user_webhook_url = f"{webhook_base.rstrip('/')}/api/persona/webhooks/{req.user_id}"
    
    headers = {
        "accept": "*/*",
        "X-API-KEY": config.ZYND_API_KEY
    }
    payload = {
        "agentId": agent_config["id"],
        "httpWebhookUrl": user_webhook_url
    }
    
    try:
        update_resp = requests.patch(
            f"{config.ZYND_REGISTRY_URL}/agents/update-webhook",
            json=payload,
            headers=headers,
            timeout=10
        )
        update_resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update webhook URL in registry: {str(e)}")

    # Note: Agent ID is locally persisted by ConfigManager in .agent-{user_id}/config.json
    # If a database profile table is added in the future, it can be updated here.

    return {
        "status": "success",
        "agent_id": agent_config["id"],
        "did": agent_config["didIdentifier"],
        "webhook_url": user_webhook_url
    }

# ── Webhook Routers (Where network messages arrive) ──────────────────

@router.post("/webhooks/{user_id}")
async def async_webhook(user_id: str, request: Request, background_tasks: BackgroundTasks):
    """
    Fire-and-forget webhook listener. 
    Receives messages from other Zynd Agents and immediately spawns a background task.
    """
    payload = await request.json()
    message = AgentMessage.from_dict(payload)
    
    background_tasks.add_task(process_async_webhook, user_id, message)
    
    return {
        "status": "received",
        "message_id": message.message_id,
        "timestamp": time.time()
    }

async def process_async_webhook(user_id: str, message: AgentMessage):
    print(f"\n[persona Async] 📥 Received Webhook {message.message_type} from {message.sender_did}")
    
    # ── INTERCEPT WRAPPER: Inbound Log ──
    t_data = None
    try:
        from supabase import create_client
        import config
        sb = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
        res1 = sb.table('dm_threads').select('id').eq("initiator_id", message.sender_did).execute()
        res2 = sb.table('dm_threads').select('id').eq("receiver_id", message.sender_did).execute()
        t_data = res1.data or res2.data
        if t_data:
            sb.table('dm_messages').insert({
                "thread_id": t_data[0]['id'],
                "sender_id": message.sender_did,
                "content": f"[Automated Ping]\n{message.content}" if message.message_type != "response" else f"[Async Reply]\n{message.content}"
            }).execute()
    except: pass

    # If it is just a response to our previous request, DO NOT execute the brain! (Prevents infinite loops)
    if message.message_type == "response":
        print("[persona Async] ✅ This was a remote reply. Database updated. Halting brain execution.")
        return

    # ── EXECUTE BRAIN (for queries) ──
    try:
        result = await handle_user_message(
            user_id=user_id,
            message=message.content,
            conversation_id=message.message_id,
            is_external=True,
            sender_did=message.sender_did
        )
        reply = result.get("reply", "I am unable to assist right now.")
    except Exception as e:
        reply = f"Error processing request: {str(e)}"
        
    print(f"[persona Async] 📤 Agent A generated async reply: {reply}")

    # ── INTERCEPT WRAPPER: Outbound Log ──
    try:
        from agent.config_manager import ConfigManager
        agent_config = ConfigManager.load_config(f".agent-{user_id}")
        my_did = agent_config.get("didIdentifier", user_id) if agent_config else user_id
        
        if t_data:
            sb.table('dm_messages').insert({
                "thread_id": t_data[0]['id'],
                "sender_id": my_did,
                "content": f"[Automated Reply]\n{reply}"
            }).execute()
    except: pass

    # ── DELIVER ASYNC REPLY BACK TO SENDER ──
    try:
        from mcp.tools.zynd_network import search_zynd_personas
        import requests, uuid, time
        import config
        
        # 1. Look up where the sender lives on the internet
        search_res = search_zynd_personas(message.sender_did, top_k=1)
        personas = search_res.get("results", [])
        if not personas:
            return
            
        target_webhook_url = personas[0].get("webhook_url")
        if not target_webhook_url:
            return
            
        # 2. Build explicit 'response' message
        response_msg = AgentMessage(
            message_id=str(uuid.uuid4()),
            sender_id=user_id,
            sender_did=my_did,
            receiver_id=message.sender_did,
            content=reply,
            message_type="response"
        )
        
        # 3. Fire back statelessly
        target_async = target_webhook_url
        if target_async.endswith("/sync"): target_async = target_async.replace("/sync", "")
        if target_async.endswith("/webhook"): target_async = target_async.replace("/webhook", "/webhook/async") # basic logic, fallback is direct URL
        
        # Try finding the base user webhooks if hitting standard Zynd structure
        if "/api/persona/webhooks" not in target_async and "/api/webhooks" not in target_async:
            pass # Keep whatever registry holds
            
        requests.post(target_async, json=response_msg.to_dict(), timeout=10)
    except Exception as e:
        print(f"[persona Async] ⚠️ Failed pushing async reply to network: {e}")

@router.post("/webhooks/{user_id}/sync", response_model=SyncWebhookResponse)
async def sync_webhook(user_id: str, request: Request):
    """
    Synchronous webhook listener. Other agents hit this when waiting for an answer.
    This passes the incoming text to our global orchestrator, but uses the
    context (connected accounts) of `user_id`.
    """
    payload = await request.json()
    try:
        message = AgentMessage.from_dict(payload)
        print(f"\n[persona Webhook] 📥 Received External Http Message from {message.sender_did}")
        print(f"[persona Webhook] 📥 Content: {message.content}")
        
        # ── INTERCEPT WRAPPER: Inbound Flow Track ──
        t_data = None
        try:
            from supabase import create_client
            import config
            sb = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
            res1 = sb.table('dm_threads').select('id').eq("initiator_id", message.sender_did).execute()
            res2 = sb.table('dm_threads').select('id').eq("receiver_id", message.sender_did).execute()
            t_data = res1.data or res2.data
            if t_data:
                sb.table('dm_messages').insert({
                    "thread_id": t_data[0]['id'],
                    "sender_id": message.sender_did,
                    "content": f"[Automated Ping]\n{message.content}"
                }).execute()
        except: pass
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid AgentMessage format: {str(e)}")
        
    # Execute through the single state-less orchestrator Brain for the specific user
    try:
        result = await handle_user_message(
            user_id=user_id,
            message=message.content,
            conversation_id=message.message_id,  # Isolate context to this interaction
            is_external=True,
            sender_did=message.sender_did
        )
        reply = result.get("reply", "I am unable to assist right now.")
        print(f"[persona Webhook] 📤 Agent A generated reply: {reply}")
        
        # ── INTERCEPT WRAPPER: Inbound Reply Track ──
        try:
            if t_data:
                from agent.config_manager import ConfigManager
                agent_config = ConfigManager.load_config(f".agent-{user_id}")
                my_did = agent_config.get("didIdentifier", user_id) if agent_config else user_id
                
                sb.table('dm_messages').insert({
                    "thread_id": t_data[0]['id'],
                    "sender_id": my_did,
                    "content": f"[Automated Reply]\n{reply}"
                }).execute()
        except: pass
        
    except Exception as e:
        reply = f"Error processing request: {str(e)}"
        print(f"[persona Webhook] ⚠️ Agent A crashed generating reply: {reply}")

    # Provide the standardized Zynd Network sync response
    return SyncWebhookResponse(
        status="success",
        message_id=message.message_id,
        response=reply,
        timestamp=time.time()
    )
