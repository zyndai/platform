"""Profile chatbot — streams Cloudflare Workers AI response for a given card handle."""
import json
import logging

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import config
from services.cards import get_card_by_handle

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    messages: list[dict]  # [{role: "user"|"assistant", content: str}]


def _build_system_prompt(card: dict) -> str:
    identity = card.get("identity", {})
    name = identity.get("name", "this person")
    headline = identity.get("headline", "")
    location = identity.get("location", "")
    summary = card.get("summary", "")
    skills = [s["name"] for s in card.get("skills", [])[:10]]
    projects = [
        f'"{p["name"]}" — {p.get("description", "")}'
        for p in card.get("projects", [])[:4]
    ]
    posts = [w.get("excerpt", "") for w in card.get("writing_samples", [])[:3]]
    working_on = card.get("working_on", [])[:3]
    can_help = card.get("can_help_with", [])[:3]
    topics = card.get("love_talking_about", [])[:3]

    lines = [
        f"You're a sharp, engaging assistant on {name}'s profile page.",
        f"People visiting want to know about {name} — to collaborate, hire, or connect.",
        "Make it feel like a real conversation, not a Wikipedia lookup.",
        "",
        f"Facts about {name}:",
        f"- Headline: {headline}" if headline else "",
        f"- Location: {location}" if location else "",
        f"- Summary: {summary}" if summary else "",
        f"- Skills: {', '.join(skills)}" if skills else "",
        f"- Working on: {', '.join(working_on)}" if working_on else "",
        f"- Can help with: {', '.join(can_help)}" if can_help else "",
        f"- Loves talking about: {', '.join(topics)}" if topics else "",
        f"- Projects: {'; '.join(projects)}" if projects else "",
        f"- Writes about: {' | '.join(posts)}" if posts else "",
        "",
        "Rules:",
        "- 2 sentences max unless they ask for more detail.",
        "- Sound like you know this person, not like you're reading their LinkedIn.",
        "- Unknown info: 'I don't have that — reach out directly.'",
        "- Never say 'As an AI' or anything robotic.",
        "- End with a follow-up question when natural.",
    ]
    return "\n".join(l for l in lines if l is not None)


async def _stream_cf(system_prompt: str, messages: list[dict]):
    url = f"https://api.cloudflare.com/client/v4/accounts/{config.CLOUDFLARE_ACCOUNT_ID}/ai/run/{config.CLOUDFLARE_AI_MODEL}"
    payload = {
        "stream": True,
        "max_tokens": 300,
        "messages": [{"role": "system", "content": system_prompt}, *messages],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            url,
            headers={"Authorization": f"Bearer {config.CLOUDFLARE_AI_KEY}", "Content-Type": "application/json"},
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                yield chunk


@router.post("/{handle}")
async def chat(handle: str, body: ChatRequest):
    if not config.CLOUDFLARE_ACCOUNT_ID or not config.CLOUDFLARE_AI_KEY:
        raise HTTPException(status_code=503, detail="Chatbot not configured")

    card_obj = get_card_by_handle(handle)
    if not card_obj:
        raise HTTPException(status_code=404, detail="Card not found")

    system_prompt = _build_system_prompt(card_obj.model_dump())

    return StreamingResponse(
        _stream_cf(system_prompt, body.messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
