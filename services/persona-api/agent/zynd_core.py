"""
Zynd AI Core — registers this agent on the Zynd AI open network.

Uses the real zyndai-agent SDK:
  - AgentConfig to define name, desc, capabilities, webhook, pricing
  - ZyndAIAgent to auto-provision identity (DID) and register
  - .set_custom_agent() to hook our orchestrator as the handler
  - Message handler for incoming requests from other agents
"""

import os
import threading
from zyndai_agent.agent import AgentConfig, ZyndAIAgent
from zyndai_agent.message import AgentMessage

import config

# ── Module-level state ───────────────────────────────────────────────
_zynd_agent: ZyndAIAgent | None = None
_agent_thread: threading.Thread | None = None


def _build_agent_config() -> AgentConfig:
    """Build the AgentConfig from our app settings."""
    return AgentConfig(
        name="ZyndNetworkingAgent",
        description=(
            "A personal AI networking assistant that manages social media "
            "(X/Twitter, LinkedIn), Google Calendar, and communications "
            "on behalf of authenticated users."
        ),
        capabilities={
            "ai": ["nlp", "social_media_management", "calendar_management"],
            "protocols": ["http"],
            "services": [
                "post_tweet",
                "read_timeline",
                "send_twitter_dm",
                "read_twitter_dms",
                "post_to_linkedin",
                "create_calendar_event",
                "list_calendar_events",
                "delete_calendar_event",
                "internet_search",
                "webpage_scrape",
            ],
        },
        webhook_host="0.0.0.0",
        webhook_port=5050,
        registry_url="https://registry.zynd.ai",
        api_key=config.ZYND_API_KEY,
        price="$0.001",          # $0.001 per request via x402
        config_dir=".agent-zynd-networking",
    )


def _message_handler(message: AgentMessage, topic: str):
    """
    Handle incoming messages from other agents on the Zynd network.

    When another agent discovers us via semantic search and sends a
    request, this handler processes it through our MCP tool system.
    """
    from mcp.server import mcp_server

    content = message.content
    result = None

    try:
        # Try to parse as a tool call: {"tool": "post_tweet", "params": {...}}
        import json
        parsed = json.loads(content) if isinstance(content, str) else content

        if isinstance(parsed, dict) and "tool" in parsed:
            tool_name = parsed["tool"]
            tool_params = parsed.get("params", {})
            result = mcp_server._call(tool_name, tool_params)
        else:
            # Plain text — use the custom agent (orchestrator) if set
            result = _zynd_agent.invoke(content) if _zynd_agent else {"error": "Agent not initialized"}

    except Exception as e:
        result = {"error": str(e)}

    # Send response back to the calling agent
    import json as _json
    response_text = _json.dumps(result, default=str) if isinstance(result, dict) else str(result)
    _zynd_agent.set_response(message.message_id, response_text)


def start_zynd_agent() -> dict:
    """
    Initialize and start the ZyndAI agent.

    Called once at server startup. The agent:
      1. Auto-provisions a DID identity on first run
      2. Registers on the Zynd registry with capabilities
      3. Starts the webhook server for incoming agent messages
      4. Hooks up the custom agent handler for invoke()

    Returns:
        dict with agent_id, webhook_url, status
    """
    global _zynd_agent, _agent_thread

    if not config.ZYND_API_KEY:
        return {
            "status": "skipped",
            "reason": "ZYND_API_KEY not set. Agent runs in local-only mode.",
        }

    try:
        agent_config = _build_agent_config()
        _zynd_agent = ZyndAIAgent(agent_config=agent_config)

        # Register the message handler for incoming network requests
        _zynd_agent.add_message_handler(_message_handler)

        # Hook up a custom agent function for invoke() calls
        def _custom_handler(input_text: str) -> str:
            """Process text through the orchestrator (imported lazily to avoid circular imports)."""
            from agent.orchestrator import handle_user_message
            import asyncio

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    handle_user_message(
                        user_id="zynd_network",
                        message=input_text,
                    )
                )
                return result.get("reply", "")
            finally:
                loop.close()

        _zynd_agent.set_custom_agent(_custom_handler)

        return {
            "status": "running",
            "agent_id": _zynd_agent.agent_id,
            "webhook_url": _zynd_agent.webhook_url,
            "pay_to_address": _zynd_agent.pay_to_address,
        }

    except Exception as e:
        return {"status": "error", "reason": str(e)}


def get_zynd_agent() -> ZyndAIAgent | None:
    """Return the running ZyndAI agent instance, or None."""
    return _zynd_agent


def search_network_agents(query: str, top_k: int = 5) -> list[dict]:
    """
    Search for other agents on the Zynd network.

    Args:
        query: Natural language description of what you're looking for
        top_k: Number of results to return

    Returns:
        List of agent metadata dicts
    """
    if not _zynd_agent:
        return []

    try:
        return _zynd_agent.search_agents_by_capabilities(
            capabilities=query.split(),
            top_k=top_k,
        )
    except Exception:
        return _zynd_agent.search_agents_by_keyword(query, limit=top_k)


def send_to_agent(webhook_url: str, message_content: str) -> dict:
    """
    Send a message to another agent on the Zynd network.
    Automatically handles x402 payments if the target agent charges.

    Args:
        webhook_url: The target agent's webhook URL
        message_content: The message to send

    Returns:
        The response from the target agent
    """
    if not _zynd_agent:
        return {"error": "Zynd agent not running"}

    try:
        msg = AgentMessage(
            content=message_content,
            sender_id=_zynd_agent.agent_id,
            message_type="query",
            sender_did=_zynd_agent.identity_credential,
        )

        # Use x402 processor for automatic payment handling
        sync_url = webhook_url.replace("/webhook", "/webhook/sync")
        response = _zynd_agent.x402_processor.post(
            sync_url,
            json=msg.to_dict(),
            timeout=60,
        )

        if response.status_code == 200:
            return response.json()
        return {"error": f"Agent returned status {response.status_code}"}

    except Exception as e:
        return {"error": str(e)}
