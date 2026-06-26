"""ZYND MCP server — exposes a user's context graph to any MCP-compatible LLM
client (Claude Desktop, IDEs, etc.). Brief §11.

Run (stdio transport):  uv run python -m app.mcp_server

Both tools are read-only. They reuse the same service layer as the REST API, so
behavior is identical across HTTP and MCP.
"""
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from app.db import close_pool, get_pool, init_pool
from app.services.control import confirm_fact, forget_fact
from app.services.export import build_jsonld_export, context_slice
from app.services.matching import match_users


@asynccontextmanager
async def lifespan(_server: FastMCP):
    await init_pool()
    try:
        yield {}
    finally:
        await close_pool()


mcp = FastMCP("zynd", lifespan=lifespan)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def get_user_context(user_id: str, topic: str, k: int = 20) -> list[dict]:
    """Return the assertions about a user most relevant to the current topic.

    Use this at the START of a session to load just the context that matters for
    what you're about to discuss — not the user's entire graph. The topic should
    be a short phrase describing the conversation subject (e.g. "Rust async
    performance", "fundraising strategy").

    Args:
        user_id: The ZYND user id (uuid).
        topic: Short phrase describing the current conversation subject.
        k: Max assertions to return (1-50; default 20).

    Returns a list of {predicate, object, object_type, confidence, relevance,
    observed_at}, ordered most-relevant first. `relevance` is cosine similarity
    (0-1) of the assertion's entity to the topic; `confidence` is how strongly
    ZYND believes the assertion holds right now (decay-adjusted).
    """
    return await context_slice(get_pool(), user_id, topic, max(1, min(k, 50)))


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def export_user_context(user_id: str) -> dict:
    """Export a user's FULL active context graph as a portable JSON-LD packet.

    Use this when you need the whole picture (portability, backup, or a broad
    profile) rather than a topic-specific slice — prefer get_user_context for
    in-conversation grounding to keep the context window small.

    Args:
        user_id: The ZYND user id (uuid).

    Returns a JSON-LD object: {@context, @type, user_id, exported_at, signature,
    assertions[]}.
    """
    return await build_jsonld_export(get_pool(), user_id)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
async def find_similar_users(user_id: str, cluster_type: str = "intent_cluster", k: int = 10) -> list[dict]:
    """Find people whose active context overlaps this user's — the matching layer.

    Use when the user wants to discover others working on / learning / believing
    similar things. `cluster_type` is one of: intent_cluster, skill_cluster,
    belief_cluster, concept_cluster, full_context. Returns users most-similar-first
    with a cosine `similarity` (0-1). Empty if the user (or candidates) have fewer
    than 5 facts in that cluster.
    """
    return await match_users(get_pool(), user_id, cluster_type, k)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
async def confirm_user_fact(user_id: str, predicate: str, object: str) -> dict:
    """Confirm a fact is true → raises its confidence to the max (0.97). Pass the
    exact predicate and object as returned by get_user_context."""
    ok = await confirm_fact(get_pool(), user_id, predicate, object)
    return {"confirmed": ok}


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False})
async def forget_user_fact(user_id: str, predicate: str, object: str) -> dict:
    """Forget a fact about the user → soft-deleted (kept for audit, no longer
    active or matched). Pass the exact predicate and object from get_user_context."""
    ok = await forget_fact(get_pool(), user_id, predicate, object)
    return {"forgotten": ok}


if __name__ == "__main__":
    mcp.run()
