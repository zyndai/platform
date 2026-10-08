"""Profile chatbot — streams Cloudflare Workers AI response for a given card handle."""
import json
import logging
import time
from collections import defaultdict

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import config
from services.card_view import build_card_view
from services.cards import get_published_card

logger = logging.getLogger(__name__)
router = APIRouter()

_RATE: dict[str, list[float]] = defaultdict(list)
_RATE_WINDOW = 60
_RATE_MAX = 20


class ChatRequest(BaseModel):
    messages: list[dict]  # [{role: "user"|"assistant", content: str}]


def _rate_ok(key: str) -> bool:
    now = time.time()
    hits = [t for t in _RATE[key] if now - t < _RATE_WINDOW]
    _RATE[key] = hits
    if len(hits) >= _RATE_MAX:
        return False
    hits.append(now)
    return True


def _build_system_prompt(view: dict) -> str:
    identity = view.get("identity") or {}
    name = identity.get("name") or "this person"
    headline = identity.get("headline") or ""
    location = identity.get("location") or ""
    summary = view.get("summary") or ""
    skills = [s.get("name") for s in (view.get("skills") or [])[:10] if isinstance(s, dict) and s.get("name")]
    working_on = (view.get("working_on") or [])[:5]
    can_help = (view.get("can_help_with") or [])[:5]
    facts = view.get("facts") or []
    fact_lines = [
        f"- {f.get('type')}: {f.get('text')} (as of {f.get('approved_at') or view.get('fresh_as_of') or 'unknown'})"
        for f in facts if isinstance(f, dict) and f.get("text")
    ]
    calendly = view.get("calendly_url")
    google_calendar = view.get("google_calendar_url")
    links = view.get("links") or {}

    lines = [
        f"You are {name}'s AI assistant on their Zynd card. You are not {name}. Never claim to be them.",
        "If asked whether you are an AI, say you are the card's AI assistant, not the person.",
        "Answer only from the facts below. If something is not listed, say you do not know. Do not invent.",
        "Talk plainly: 1-3 short sentences. No markdown, no theatrics.",
        "",
        f"About {name}:",
        f"- Headline: {headline}" if headline else "",
        f"- Location: {location}" if location else "",
        f"- Summary: {summary}" if summary else "",
        f"- Skills: {', '.join(skills)}" if skills else "",
        f"- Working on: {', '.join(working_on)}" if working_on else "",
        f"- Can help with: {', '.join(can_help)}" if can_help else "",
        "Approved facts:" if fact_lines else "",
        *fact_lines,
        f"- Calendly: {calendly}" if calendly else "",
        f"- Google Calendar: {google_calendar}" if google_calendar else "",
        f"- GitHub: {links.get('github')}" if links.get("github") else "",
        f"- LinkedIn: {links.get('linkedin')}" if links.get("linkedin") else "",
        f"- Website: {links.get('website')}" if links.get("website") else "",
        "",
        "If they want to get in touch, share a booking URL if one is listed, otherwise tell them to request an intro on this page.",
        "Match the visitor's language.",
    ]
    return "\n".join(line for line in lines if line)


def _clean_artifacts(text: str) -> str:
    return (
        text.replace("**", "")
        .replace("`", "")
        .replace("#", "")
        .replace("*", "")
        .replace("—", "-")
        .replace("–", "-")
    )


CLOUDFLARE_MODEL = "@cf/deepseek-ai/deepseek-v4-flash-0731"


async def _stream_cf(system_prompt: str, messages: list[dict]):
    url = f"https://api.cloudflare.com/client/v4/accounts/{config.CLOUDFLARE_ACCOUNT_ID}/ai/run/{CLOUDFLARE_MODEL}"
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
            buf = ""
            async for chunk in resp.aiter_text():
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        continue
                    try:
                        data = json.loads(data_str)
                        content = (data.get("choices") or [{}])[0].get("delta", {}).get("content")
                        if content:
                            yield f"data: {json.dumps({'response': _clean_artifacts(content)})}\n\n"
                    except Exception:
                        continue
    yield "data: [DONE]\n\n"


@router.post("/{handle}")
async def chat(handle: str, body: ChatRequest, request: Request):
    if not config.CLOUDFLARE_ACCOUNT_ID or not config.CLOUDFLARE_AI_KEY:
        raise HTTPException(status_code=503, detail="Chatbot not configured")

    found = get_published_card(handle)
    if not found:
        raise HTTPException(status_code=404, detail="Card not found")
    card, claimed = found
    if not claimed or getattr(card, "hidden_from_agents", False):
        raise HTTPException(status_code=404, detail="Chat is not available on this card")

    ip = request.client.host if request.client else "unknown"
    if not _rate_ok(f"{ip}:{handle}"):
        raise HTTPException(status_code=429, detail="Too many messages. Try again in a minute.")

    view = build_card_view(card, claimed=claimed)
    system_prompt = _build_system_prompt(view)

    return StreamingResponse(
        _stream_cf(system_prompt, body.messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
