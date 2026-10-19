"""ChatGPT plugin tools. Registered on the memory MCP only for client zynd-chatgpt-plugin."""
from __future__ import annotations

from fastmcp.dependencies import CurrentAccessToken, Depends
from fastmcp.server.auth import AccessToken

from app.config import settings
from app.services.findability import get_card

import plugin_consent

PLUGIN_SCOPES = ("memory:recall", "memory:propose", "cards:review")
PLUGIN_TOOLS = {
    "recall_memories": "memory:recall",
    "propose_memory": "memory:propose",
    "get_proposal_status": "memory:propose",
    "list_pending_facts": "cards:review",
    "propose_card_fact": "cards:review",
    "get_public_card": "cards:review",
}
_MAX_QUERY = 500


def plugin_tool_visible(name: str, scopes: list[str]) -> bool:
    return name in PLUGIN_TOOLS and PLUGIN_TOOLS[name] in scopes


def is_plugin(token) -> bool:
    return bool(token and (token.claims or {}).get("oauth_client_id") == settings.plugin_oauth_client_id)


def register(mcp, get_pool, get_arq, uid_dep) -> None:
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def recall_memories(query: str, limit: int = 5, uid: str = Depends(uid_dep)) -> dict:
        """Recall relevant private ZYND facts only when the owner asks about them."""
        query = query.strip()
        if not query or len(query) > _MAX_QUERY:
            raise ValueError("query must contain 1 to 500 characters")
        if not settings.feature_plugin_consent:
            raise PermissionError("ZYND plugin consent flow is unavailable")
        facts = await plugin_consent.recall_facts(
            await get_pool(), uid, query, max(1, min(limit, 10)))
        return {"facts": facts, "private": True}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
    async def propose_memory(text: str, uid: str = Depends(uid_dep),
                             token: AccessToken = CurrentAccessToken()) -> dict:
        """Draft one private fact for separate owner review on ZYND; this does not save it."""
        if not settings.feature_plugin_consent:
            raise PermissionError("ZYND plugin consent flow is unavailable")
        return await plugin_consent.create_proposal(
            await get_pool(), await get_arq(), uid, "save_memory", text,
            source_connection_id=(token.claims or {}).get("jti"),
            source_client_id=(token.claims or {}).get("oauth_client_id"))

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def get_proposal_status(proposal_id: str, uid: str = Depends(uid_dep)) -> dict:
        """Read the status of your pending private or public fact proposal."""
        if not settings.feature_plugin_consent:
            raise PermissionError("ZYND plugin consent flow is unavailable")
        return await plugin_consent.get_status(
            await get_pool(), await get_arq(), uid, proposal_id)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
    async def propose_card_fact(fact_id: str, version: int, uid: str = Depends(uid_dep),
                                token: AccessToken = CurrentAccessToken()) -> dict:
        """Queue one existing private card fact for exact-wording review; never publish it."""
        if not settings.feature_plugin_consent:
            raise PermissionError("ZYND plugin consent flow is unavailable")
        return await plugin_consent.create_card_proposal(
            await get_pool(), await get_arq(), uid, fact_id, version,
            source_connection_id=(token.claims or {}).get("jti"),
            source_client_id=(token.claims or {}).get("oauth_client_id"))

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def list_pending_facts(uid: str = Depends(uid_dep)) -> dict:
        """Private card facts and open proposals. Do not publish them."""
        if not settings.feature_plugin_consent:
            raise PermissionError("ZYND plugin consent flow is unavailable")
        return await plugin_consent.list_pending(await get_pool(), await get_arq(), uid)

    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def get_public_card(uid: str = Depends(uid_dep)) -> dict:
        """Return only facts already approved for the public findability card."""
        if not settings.feature_plugin_consent:
            raise PermissionError("ZYND plugin consent flow is unavailable")
        return {"facts": await get_card(await get_pool(), uid)}


