import asyncio

from fastapi import APIRouter, HTTPException, Query

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
):
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
    )
    return {
        "query": {
            "q": q,
            "role": role,
            "location": location,
            "skills": skills,
            "industry": industry,
            "availability": availability,
            "experience_min": experience_min,
        },
        "searchable_attributes": SEARCHABLE_ATTRIBUTES,
        "results": results,
    }


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    card = await asyncio.to_thread(cards_service.get_card, agent_id)
    if not card:
        raise HTTPException(status_code=404, detail="agent not found")
    return card.model_dump(mode="json")
