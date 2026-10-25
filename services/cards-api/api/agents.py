import asyncio

from fastapi import APIRouter, HTTPException, Query, Request

import config
from services import cards as cards_service
from services import events as events_service
from services import lookup as lookup_service
from services import search as search_service

router = APIRouter()

SEARCHABLE_ATTRIBUTES = [
    {"name": "q", "type": "string", "description": "Free-text / natural-language query"},
    {"name": "role", "type": "string", "description": "Job role or headline (e.g. 'GTM Engineer')"},
    {"name": "skills", "type": "string", "description": "Comma-separated skills (e.g. 'rust, zero-knowledge')"},
    {"name": "location", "type": "string", "description": "City or region (e.g. 'Bangalore')"},
    {"name": "industry", "type": "string", "description": "Industry (e.g. 'AI', 'fintech')"},
    {"name": "availability", "type": "string", "description": "fulltime | contract | freelance | open"},
    {"name": "experience_min", "type": "integer", "description": "Minimum years of experience"},
    {"name": "include_unclaimed", "type": "boolean", "description": "Include unclaimed (scraped) cards; default false for agent callers"},
    {"name": "topics", "type": "string", "description": "Comma-separated topics: they raise the score of cards that mention them and never remove a card (unlike skills)"},
    {"name": "relax", "type": "boolean", "description": "If fewer than `limit` cards pass every filter, loosen skills, then location, then role; looser matches rank last and carry `relaxed`"},
    {"name": "less_like", "type": "string", "description": "Comma-separated Card handles the searcher wants to see less of"},
    {"name": "as_handle", "type": "string", "description": "The searcher's own Card handle: results who want to meet people like them rank higher"},
]


def _record_search(request: Request, results: list[dict], *, has_query: bool, **filters: str) -> None:
    """Top of the networking funnel (docs/cards/s04-funnel.sql): how many searches, how many
    people came back, which ones. No query text and no caller identity is stored."""
    events_service.emit(
        "search",
        request=request,
        meta={
            "n": len(results),
            "top": [r["handle"] for r in results[:5] if r.get("handle")],
            "filters": sorted(name for name, value in filters.items() if value),
            "text": has_query,
        },
    )


@router.get("/search")
async def search_agents(
    request: Request,
    q: str = Query("", max_length=200),
    role: str = Query("", max_length=100),
    location: str = Query("", max_length=100),
    skills: str = Query("", max_length=200),
    industry: str = Query("", max_length=100),
    availability: str = Query("", max_length=20),
    experience_min: int | None = Query(None, ge=0),
    limit: int = Query(10, ge=1, le=50),
    include_unclaimed: bool = Query(False),
    as_handle: str = Query("", max_length=64),
    less_like: str = Query("", max_length=700),
    topics: str = Query("", max_length=200),
    relax: bool = Query(False),
):
    keep_unclaimed = include_unclaimed or not config.FEATURE_S03_UNCLAIMED_TIERING
    searcher = await asyncio.to_thread(cards_service.get_card_by_handle, as_handle.strip().lstrip("@")) if as_handle.strip() else None
    disliked = [c for c in (await asyncio.to_thread(cards_service.get_card_by_handle, h.strip().lstrip("@"))
                            for h in less_like.split(",")[:10] if h.strip()) if c] if less_like.strip() else []
    results = await asyncio.to_thread(
        search_service.search_agents,
        q,
        role,
        location,
        skills,
        industry,
        availability,
        experience_min,
        limit,
        keep_unclaimed,
        searcher,
        disliked or None,
        **({"topics": topics} if topics else {}),
        **({"relax": True} if relax else {}),
    )
    claimed = cards_service.claimed_by_handles([r["handle"] for r in results if r.get("handle")])
    kept = []
    for r in results:
        if r.get("handle"):
            r["claimed"] = claimed.get(r["handle"], False)
        if keep_unclaimed or r.get("claimed") is True:
            kept.append(r)
    results = kept
    from services import trust
    verified = trust.verified_by_card_ids([r["agent_id"] for r in results if r.get("agent_id")])
    for r in results:
        if verified:
            r["verified"] = verified.get(r.get("agent_id"), [])
    _record_search(request, results, role=role, location=location, skills=skills,
                   industry=industry, availability=availability, has_query=bool(q.strip()))
    return {
        "query": {
            "q": q,
            "role": role,
            "location": location,
            "skills": skills,
            "topics": topics,
            "relax": relax,
            "industry": industry,
            "availability": availability,
            "experience_min": experience_min,
            "include_unclaimed": include_unclaimed,
        },
        "searchable_attributes": SEARCHABLE_ATTRIBUTES,
        "results": results,
    }


@router.get("/lookup")
async def lookup_agents(
    request: Request,
    name: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(5, ge=1, le=10),
    include_unclaimed: bool = Query(False),
):
    """Find one specific person by name or handle. Public Card data only (the same as /search):
    no contact fields. Exact full-name match first, then a name that starts with the text, then
    one that contains it."""
    if not lookup_service.allow(request):
        raise HTTPException(status_code=429, detail="too many lookups, try again in a minute")
    keep_unclaimed = include_unclaimed or not config.FEATURE_S03_UNCLAIMED_TIERING
    results = await asyncio.to_thread(lookup_service.lookup_by_name, name.strip().lstrip("@"), limit, keep_unclaimed)
    claimed = cards_service.claimed_by_handles([r["handle"] for r in results if r.get("handle")])
    for r in results:
        r["claimed"] = claimed.get(r.get("handle"), False)
    from services import trust
    verified = trust.verified_by_card_ids([r["agent_id"] for r in results if r.get("agent_id")])
    for r in results:
        if verified:
            r["verified"] = verified.get(r.get("agent_id"), [])
    _record_search(request, results, has_query=True, name="lookup")
    return {"query": {"name": name, "include_unclaimed": include_unclaimed}, "results": results}


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    """One agent profile. Unclaimed (scraped, no owner) cards are hidden from
    agents by default — same as /v1/agents/search — when S03 tiering is on.
    Always a CardView so agents see the same facts as /view, data.json, and chat."""
    card = await asyncio.to_thread(cards_service.get_card, agent_id)
    if not card:
        raise HTTPException(status_code=404, detail="agent not found")
    claimed = cards_service.card_is_claimed(card.handle) if card.handle else True
    if claimed is False and config.FEATURE_S03_UNCLAIMED_TIERING:
        raise HTTPException(status_code=404, detail="agent not found")
    from services.card_view import build_card_view

    return build_card_view(card, claimed=bool(claimed))
