import asyncio

from fastapi import APIRouter, HTTPException, Query

import config
from services import cards as cards_service
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
]


@router.get("/search")
async def search_agents(
    q: str = Query("", max_length=200),
    role: str = Query("", max_length=100),
    location: str = Query("", max_length=100),
    skills: str = Query("", max_length=200),
    industry: str = Query("", max_length=100),
    availability: str = Query("", max_length=20),
    experience_min: int | None = Query(None, ge=0),
    limit: int = Query(10, ge=1, le=50),
    include_unclaimed: bool = Query(False),
):
    keep_unclaimed = include_unclaimed or not config.FEATURE_S03_UNCLAIMED_TIERING
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
    )
    claimed = cards_service.claimed_by_handles([r["handle"] for r in results if r.get("handle")])
    kept = []
    for r in results:
        if r.get("handle"):
            r["claimed"] = claimed.get(r["handle"], False)
        if keep_unclaimed or r.get("claimed") is True:
            kept.append(r)
    results = kept
    return {
        "query": {
            "q": q,
            "role": role,
            "location": location,
            "skills": skills,
            "industry": industry,
            "availability": availability,
            "experience_min": experience_min,
            "include_unclaimed": include_unclaimed,
        },
        "searchable_attributes": SEARCHABLE_ATTRIBUTES,
        "results": results,
    }


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
