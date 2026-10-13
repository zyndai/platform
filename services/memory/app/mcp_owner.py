"""Owner tools on the shared ZYND MCP server (S09 cards toolset).

approve_fact refuses unless the token has cards:approve and confirm=true.
"""
from __future__ import annotations

from fastmcp.dependencies import Depends

from app.services.findability import (
    ENUM_VALUES,
    approve,
    declare,
    dismiss,
    get_suggestions,
)
from app.services.mcp_scopes import approve_gate


def register(mcp, uid_dep) -> None:
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def list_intros(uid: str = Depends(uid_dep)) -> dict:
        """Read my inbound intro requests. Human owners make decisions in the UI."""
        from app.mcp_http import _get_pool
        from app.tools.card_intros import get_owner_intros
        return await get_owner_intros(await _get_pool(), uid)

    # get_card_status and get_card_activity already exist (S10). ScopeGate
    # hides them unless the token has cards:read or the legacy user scope.
    @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    async def list_pending_facts(uid: str = Depends(uid_dep)) -> dict:
        """Facts waiting for the owner to approve. Do not publish them yourself."""
        from app.mcp_http import _get_pool
        rows = await get_suggestions(await _get_pool(), uid)
        data = [
            {"predicate": r.get("predicate"), "object": r.get("object"), "group": r.get("group")}
            for r in rows
        ]
        return {"ok": True, "data": data, "next_actions": ["Ask the owner before approving"]}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
    async def approve_fact(
        predicate: str,
        object: str,
        confirm: bool = False,
        uid: str = Depends(uid_dep),
    ) -> dict:
        """Publish one fact. Requires the cards:approve scope and confirm=true from the owner."""
        from fastmcp.server.dependencies import get_access_token
        token = get_access_token()
        scopes = list(token.scopes) if token else []
        gate = approve_gate(scopes, confirm)
        if gate:
            return {
                "ok": False,
                "error": gate,
                "next_actions": ["Ask the owner to confirm in the Zynd card UI"],
            }
        from app.mcp_http import _get_pool
        result = await approve(await _get_pool(), uid, predicate, object)
        if not result:
            return {"ok": False, "error": "not_found"}
        return {"ok": True, "data": {"status": result.get("status")}}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
    async def dismiss_fact(
        predicate: str,
        object: str,
        confirm: bool = False,
        uid: str = Depends(uid_dep),
    ) -> dict:
        """Hide one inbox fact. Requires cards:approve and confirm=true."""
        from fastmcp.server.dependencies import get_access_token
        token = get_access_token()
        scopes = list(token.scopes) if token else []
        gate = approve_gate(scopes, confirm)
        if gate:
            return {"ok": False, "error": gate}
        from app.mcp_http import _get_pool
        ok = await dismiss(await _get_pool(), uid, predicate, object)
        return {"ok": bool(ok), "error": None if ok else "not_found"}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
    async def set_looking_for(
        text: str,
        expires_in_days: int = 7,
        uid: str = Depends(uid_dep),
    ) -> dict:
        """Publish a looking-for value. Only the fixed seeking list is public; other text stays private."""
        from app.mcp_http import _get_pool
        pool = await _get_pool()
        value = (text or "").strip()
        allowed = ENUM_VALUES["is_seeking"]
        if value in allowed:
            await declare(pool, uid, "is_seeking", value)
            return {"ok": True, "data": {"predicate": "is_seeking", "expires_in_days": 7}}
        from app.services.findability import declare_private
        await declare_private(pool, uid, "intends_to", value)
        return {
            "ok": True,
            "data": {"predicate": "intends_to", "public": False, "expires_in_days": expires_in_days},
            "next_actions": [f"Public looking-for must be one of: {', '.join(sorted(allowed))}"],
        }

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
    async def update_headline(text: str, uid: str = Depends(uid_dep)) -> dict:
        """The public headline lives on the card editor, not in memory."""
        del text, uid
        return {
            "ok": False,
            "error": "edit_on_card",
            "next_actions": ["Change the headline on the Zynd card edit page"],
        }

    @mcp.prompt
    def weekly_card_review() -> str:
        """Walk the owner through private facts. Never approve without a yes."""
        return (
            "Review this week's private facts with list_pending_facts. "
            "Do not call approve_fact unless the owner confirms and this connection "
            "has the cards:approve scope."
        )
