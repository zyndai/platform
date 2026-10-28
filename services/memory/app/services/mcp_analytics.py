"""Public-card reads returned by MCP, with advertised client attribution only."""
import logging
import re

import httpx
from fastmcp.server.dependencies import get_context, get_http_headers

from app.config import settings

logger = logging.getLogger(__name__)
EVENT_BATCH_SIZE = 20
EVENT_TIMEOUT_SECONDS = 5
MCP_CLIENT_INFO_KEY = "io.modelcontextprotocol/clientInfo"
SERVER_EVENT_HEADER = "X-Zynd-Server-Event"
CLIENT_LABELS = {
    "codex": "Codex", "chatgpt": "ChatGPT-MCP", "claude": "Claude-MCP",
    "perplexity": "Perplexity-MCP",
}


def advertised_user_agent() -> str:
    """Forward no credentials. An unidentified MCP client is never called ChatGPT."""
    ua = get_http_headers().get("user-agent", "")[:512]
    label = "Zynd-MCP"
    try:
        context = get_context()
        params = context.session.client_params
        info = getattr(params, "client_info", None) or getattr(params, "clientInfo", None)
        name = getattr(info, "name", "")
        if not name:
            # Newer MCP clients send identity per request instead of initialize.
            meta = getattr(context.request_context, "meta", None)
            info = meta.get(MCP_CLIENT_INFO_KEY) if isinstance(meta, dict) else None
            name = info.get("name", "") if isinstance(info, dict) else ""
        if not isinstance(name, str):
            name = ""
        words = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
        label = next((value for key, value in CLIENT_LABELS.items() if key in words), label)
    except (RuntimeError, AttributeError):
        # Direct unit calls and transports without an initialized session.
        pass
    return f"{ua} {label}".strip()


async def record_fetches(handles: list[str | None], *, endpoint: str, tool: str, category: str = "card") -> None:
    """Count returned cards, including cached reads; never log queries or caller IDs."""
    if not settings.cards_api_base_url:
        logger.warning("MCP card analytics unavailable endpoint=%s tool=%s", endpoint, tool)
        return
    unique = list(dict.fromkeys(handles))
    try:
        headers = {"User-Agent": advertised_user_agent()}
        if settings.events_server_token:
            headers[SERVER_EVENT_HEADER] = settings.events_server_token
        async with httpx.AsyncClient(timeout=EVENT_TIMEOUT_SECONDS) as client:
            for start in range(0, len(unique), EVENT_BATCH_SIZE):
                response = await client.post(
                    f"{settings.cards_api_base_url.rstrip('/')}/events",
                    headers=headers,
                    json={"events": [{"event": "agent_fetch", "handle": handle,
                          "meta": {"endpoint": endpoint, "tool": tool, "category": category}}
                         for handle in unique[start:start + EVENT_BATCH_SIZE]]},
                )
                response.raise_for_status()
        logger.info("MCP card analytics recorded endpoint=%s tool=%s profiles=%d", endpoint, tool, len(unique))
    except httpx.HTTPStatusError as exc:
        logger.warning("MCP card analytics delivery failed endpoint=%s tool=%s status=%d",
                       endpoint, tool, exc.response.status_code)
    except Exception:
        logger.warning("MCP card analytics delivery failed endpoint=%s tool=%s", endpoint, tool)


async def record_people(result: dict, *, endpoint: str, tool: str) -> None:
    # find_people assigns a handle only when a person has a published Card.
    # `sources` says how they were found (including Zynd similarity), and
    # `claimed` controls connection eligibility. Neither decides whether the
    # returned profile was read. External people without Cards have no handle.
    handles = [p["handle"].strip() for p in result.get("people", [])
               if isinstance(p, dict) and isinstance(p.get("handle"), str)
               and p["handle"].strip()]
    if handles:
        await record_fetches(handles, endpoint=endpoint, tool=tool, category="search_result")
