import requests
import time
import uuid

import config
from zyndai_agent.message import AgentMessage
from zyndai_agent.config_manager import ConfigManager

def search_zynd_personas(query: str, top_k: int = 5) -> dict:
    """
    Search the Zynd AI registry for other public agent personas.
    All personas have a tag "persona" so it should be used in order to not return any other agents.
    
    Args:
        query: Name, keyword, or capabilities to search for (e.g., 'Alice' or 'Calendar Management').
        top_k: Max results to return.
    """
    if not config.ZYND_API_KEY:
        return {"error": "ZYND_API_KEY not configured."}

    import json
    try:
        url = f"{config.ZYND_REGISTRY_URL}/agents"
        
        # Normalize generic LLM queries so they properly match the 'persona' services tag in the registry
        if query.lower().strip() in ["all", "any", "everyone", "personas", "agents", "network", "list"]:
            query = "persona"
            
        print(f"[zynd_network] Searching registry at {url} with keyword: '{query}'")
        
        # We start with keyword search to look for exact Names or Descriptions
        resp = requests.get(url, params={
            "keyword": query,
            "limit": top_k
        })
        resp.raise_for_status()
        
        response_data = resp.json()
        agents = response_data.get("data", []) if isinstance(response_data, dict) else response_data
        print(f"[zynd_network] Discovered {len(agents)} raw agents from registry.")
        
        # Filter out anything that isn't a tagged networking Persona
        personas = []
        for a in agents:
            caps = a.get("capabilities", {})
            # Zynd registry stringifies capabilities dicts, so we must unpack them safely
            if isinstance(caps, str):
                try:
                    caps = json.loads(caps)
                except:
                    caps = {}
            
            # Allow wildcard name matching, or strict 'persona' service matching
            is_persona = False
            if isinstance(caps, dict) and "persona" in caps.get("services", []):
                is_persona = True
            elif "persona" in str(caps).lower():
                is_persona = True
                
            if is_persona:
                personas.append({
                    "name": a.get("name"),
                    "did": a.get("didIdentifier"),
                    "description": a.get("description"),
                    "allowed_capabilities": caps.get("ai", []) if isinstance(caps, dict) else [],
                    "webhook_url": a.get("httpWebhookUrl")
                })

        print(f"[zynd_network] Filtered down to {len(personas)} platform Personas.")

        return {"status": "success", "results": personas}
    except Exception as e:
        return {"error": str(e)}

def message_zynd_agent(user_id: str, target_webhook_url: str, target_did: str, message: str) -> dict:
    """
    Send a structured message to another user's persona on the Zynd network to negotiate or request an action.
    
    Args:
        user_id: The ID of the user sending the message (injected automatically).
        target_webhook_url: The webhook URL of the agent you want to message (obtained from search_zynd_personas).
        target_did: The exact DID of the agent you are messaging (obtained from search_zynd_personas).
        message: The natural language request you are sending to the other agent (e.g. "I am booking a calendar meeting for my user John").
    """
    # Load our sender identity
    config_dir = f".agent-{user_id}"
    agent_config = ConfigManager.load_config(config_dir)
    sender_did = agent_config["didIdentifier"] if agent_config else "anonymous"
    sender_id = agent_config["id"] if agent_config else "anonymous"
    
    msg = AgentMessage(
        message_id=str(uuid.uuid4()),
        sender_id=sender_id,
        sender_did=sender_did,
        receiver_id=target_did,
        content=message,
        message_type="query"
    )
    
    if not target_webhook_url:
        return {"error": "The target agent does not have a webhook URL currently configured. They cannot receive messages."}
        
    # Fire statelessly to the standard asynchronous webhook.
    sync_url = target_webhook_url
        
    try:
        print(f"\n[zynd_network] 🚀 Agent B sending external ASYNC webhook to: {sync_url}")
        print(f"[zynd_network] 🚀 Payload msg: '{message}'")
        
        # ── INTERCEPT WRAPPER: Outbound Sync ──
        # Let's map our secret autonomous AI actions neatly into the DM table so users see them
        from supabase import create_client
        sb = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
        t_data = None
        try:
           res1 = sb.table('dm_threads').select('id').in_("initiator_id", [sender_did, user_id]).eq("receiver_id", target_did).execute()
           res2 = sb.table('dm_threads').select('id').eq("initiator_id", target_did).in_("receiver_id", [sender_did, user_id]).execute()
           t_data = res1.data or res2.data
           if t_data:
               sb.table('dm_messages').insert({
                   "thread_id": t_data[0]['id'], 
                   "sender_id": sender_did, 
                   "content": f"[Automated Ping]\n{message}"
               }).execute()
        except: pass
        
        resp = requests.post(sync_url, json=msg.to_dict(), timeout=30)
        resp.raise_for_status()
        result_json = resp.json()
        print(f"[zynd_network] 🎯 Agent A Responded Sync: {result_json}")
        
        
        return {"status": "success", "message": "The message was successfully transmitted asynchronously to the target agent.", "response": result_json}
    except Exception as e:
        return {"error": str(e)}
