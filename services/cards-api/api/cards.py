import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Query

import config
from api.auth import verify_supabase_jwt
from models.card import AgentProfileCard
from services import cards as cards_service


def _validate_linkedin_url(u: str) -> str:
    """Validate that u is a safe https linkedin.com URL, reject SSRF vectors."""
    p = urlparse(u)
    if p.scheme != "https":
        raise HTTPException(status_code=422, detail="linkedin URL must use https")
    host = (p.hostname or "").lower().rstrip(".")
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        raise HTTPException(status_code=422, detail="URL must be a linkedin.com address")
    try:
        for res in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(res[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise HTTPException(status_code=422, detail="disallowed host")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=422, detail="could not resolve linkedin.com host")
    return u

router = APIRouter()


@router.get("")
async def search_cards(q: str = Query("", max_length=200)):
    if q:
        cards = cards_service.search_cards(q)
    else:
        cards = cards_service.list_published()
    return [c.model_dump(mode="json") for c in cards]


# /mine must come before /{card_id} so FastAPI doesn't match "mine" as a card_id
@router.get("/mine")
async def get_my_card(authorization: str | None = Header(default=None)):
    principal = verify_supabase_jwt(authorization)
    if not principal:
        raise HTTPException(status_code=401, detail="Unauthorized")
    result = await asyncio.to_thread(cards_service.get_card_by_owner, principal.email)
    if not result:
        return None
    card, handle = result
    return {"card": card.model_dump(mode="json"), "handle": handle}


@router.get("/handle-available/{handle}")
async def check_handle_available(handle: str):
    """Returns {available: bool, slug: str} for a proposed custom handle."""
    import re
    slug = re.sub(r"[^a-z0-9-]", "", handle.lower())[:30].strip("-")
    if len(slug) < 2:
        return {"available": False, "slug": slug, "reason": "too short"}
    sb = config.get_supabase()
    resp = sb.table("agent_profile_cards").select("id").eq("handle", slug).execute()
    return {"available": not resp.data, "slug": slug}


@router.get("/by-handle/{handle}")
async def get_card_by_handle(handle: str):
    card = await asyncio.to_thread(cards_service.get_card_by_handle, handle)
    if not card:
        raise HTTPException(status_code=404, detail="card not found")
    return card.model_dump(mode="json")


@router.patch("/by-handle/{handle}")
async def patch_card(
    handle: str,
    body: dict,
    authorization: str | None = Header(default=None),
    x_claim_token: str | None = Header(default=None),
):
    principal = verify_supabase_jwt(authorization)
    if not principal:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # Extract new_handle before model validation (not a card field)
    new_handle: str | None = body.pop("new_handle", None)
    try:
        card = AgentProfileCard.model_validate(body)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid card data: {exc}") from exc
    owner_user_id = principal.sub if principal.iss == config.AAFO_ISSUER else None
    ok, effective_handle = await asyncio.to_thread(
        cards_service.update_card, handle, card, principal.email, new_handle, x_claim_token, owner_user_id
    )
    if not ok:
        raise HTTPException(status_code=403, detail="Not the card owner")
    result = card.model_dump(mode="json")
    result["handle"] = effective_handle
    return result


class RefreshLinkedInBody(dict):
    pass


@router.post("/by-handle/{handle}/refresh-linkedin")
async def refresh_linkedin(
    handle: str,
    body: dict = {},
    authorization: str | None = Header(default=None),
):
    """Re-scrape LinkedIn for an existing card and update work_experience.

    Body (optional JSON): {"linkedin_url": "https://linkedin.com/in/handle"}
    Falls back to the URL stored in card.identity.links.linkedin.
    """
    principal = verify_supabase_jwt(authorization)
    if not principal:
        raise HTTPException(status_code=401, detail="Unauthorized")

    card = await asyncio.to_thread(cards_service.get_card_by_handle, handle)
    if not card:
        raise HTTPException(status_code=404, detail="card not found")

    linkedin_url = (
        (body or {}).get("linkedin_url")
        or (card.identity.links or {}).get("linkedin")
        or ""
    )
    if not linkedin_url:
        raise HTTPException(status_code=422, detail="no LinkedIn URL — pass {\"linkedin_url\": \"https://linkedin.com/in/handle\"} in body")
    linkedin_url = _validate_linkedin_url(linkedin_url)

    from scraping import linkedin as linkedin_scraper
    _, stats = await linkedin_scraper.fetch_linkedin_profile(linkedin_url)
    work_experience = (stats or {}).pop("work_experience_raw", None) if stats else None
    if not work_experience:
        raise HTTPException(status_code=422, detail="no work experience data returned by LinkedIn scraper")

    # Patch only work_experience — avoids re-embedding the full card
    sb = config.get_supabase()
    from services.jobs import utcnow
    stored = (
        sb.table("agent_profile_cards").select("card,owner_email").eq("handle", handle).execute()
    )
    if not stored.data:
        raise HTTPException(status_code=404, detail="card not found")
    row = stored.data[0]
    stored_owner = row.get("owner_email")
    if not stored_owner:
        raise HTTPException(status_code=403, detail="claim this card before refreshing it")
    if stored_owner.lower() != principal.email.lower():
        raise HTTPException(status_code=403, detail="not the card owner")

    card_json = row["card"]
    card_json["work_experience"] = work_experience
    card_json["updated_at"] = utcnow()
    sb.table("agent_profile_cards").update(
        {"card": card_json, "updated_at": card_json["updated_at"]}
    ).eq("handle", handle).execute()

    return {"work_experience": work_experience}


@router.post("/by-handle/{handle}/refresh-github")
async def refresh_github(
    handle: str,
    body: dict = {},
    authorization: str | None = Header(default=None),
):
    """Re-scrape GitHub for an existing card and update github_stats + contribution_stats.

    Body (optional JSON): {"github_handle": "octocat"}
    Falls back to the handle stored in card.identity.links.github.
    """
    principal = verify_supabase_jwt(authorization)
    if not principal:
        raise HTTPException(status_code=401, detail="Unauthorized")

    card = await asyncio.to_thread(cards_service.get_card_by_handle, handle)
    if not card:
        raise HTTPException(status_code=404, detail="card not found")

    github_handle = (body or {}).get("github_handle") or ""
    if not github_handle:
        from urllib.parse import urlparse
        gh_url = (card.identity.links or {}).get("github") or ""
        if gh_url:
            parts = urlparse(gh_url).path.strip("/").split("/")
            github_handle = parts[0] if parts else ""
    if not github_handle:
        raise HTTPException(status_code=422, detail="no GitHub handle — pass {\"github_handle\": \"octocat\"} in body")

    from scraping import github as github_scraper
    github_data = await github_scraper.fetch_github(github_handle)
    if not github_data:
        raise HTTPException(status_code=422, detail="GitHub scrape returned no data")

    github_stats = github_data.get("stats")  # scraper key is "stats", not "github_stats"
    contribution_stats = github_data.get("contribution_stats")
    github_url = (github_data.get("user") or {}).get("html_url") or f"https://github.com/{github_handle}"

    sb = config.get_supabase()
    from services.jobs import utcnow
    stored = (
        sb.table("agent_profile_cards").select("card,owner_email").eq("handle", handle).execute()
    )
    if not stored.data:
        raise HTTPException(status_code=404, detail="card not found")
    row = stored.data[0]
    stored_owner = row.get("owner_email")
    if not stored_owner:
        raise HTTPException(status_code=403, detail="claim this card before refreshing it")
    if stored_owner.lower() != principal.email.lower():
        raise HTTPException(status_code=403, detail="not the card owner")

    card_json = row["card"]
    if github_stats:
        card_json["github_stats"] = github_stats
    if contribution_stats:
        card_json["contribution_stats"] = contribution_stats
    card_json.setdefault("identity", {}).setdefault("links", {})["github"] = github_url
    card_json["updated_at"] = utcnow()
    sb.table("agent_profile_cards").update(
        {"card": card_json, "updated_at": card_json["updated_at"]}
    ).eq("handle", handle).execute()

    return {"github_stats": github_stats, "contribution_stats": contribution_stats}


@router.post("/by-handle/{handle}/refresh-memory")
async def refresh_memory(
    handle: str,
    authorization: str | None = Header(default=None),
):
    """Refresh the card's ZYND memory snapshot from the memory layer.

    Called by the dashboard right after a user claims a card so their key
    points (public findability facts) show up immediately instead of waiting
    for the 6-hourly cron. Owner-only.
    """
    principal = verify_supabase_jwt(authorization)
    if not principal:
        raise HTTPException(status_code=401, detail="Unauthorized")

    card = await asyncio.to_thread(cards_service.get_card_by_handle, handle)
    if not card:
        raise HTTPException(status_code=404, detail="card not found")

    sb = config.get_supabase()
    stored = (
        sb.table("agent_profile_cards").select("owner_email").eq("handle", handle).execute()
    )
    if not stored.data:
        raise HTTPException(status_code=404, detail="card not found")
    stored_owner = stored.data[0].get("owner_email")
    if not stored_owner:
        raise HTTPException(status_code=403, detail="claim this card before refreshing it")
    if stored_owner.lower() != principal.email.lower():
        raise HTTPException(status_code=403, detail="not the card owner")

    from services.zynd_memory import fetch_findability
    payload = fetch_findability(principal.email)
    zynd_memory: list[dict] | None = None
    if payload and payload.get("connected"):
        zynd_memory = payload.get("facts") or []
    ok = await asyncio.to_thread(cards_service.update_card_memory, handle, zynd_memory)
    if not ok:
        raise HTTPException(status_code=404, detail="card not found")
    return {"zynd_memory": zynd_memory}


@router.get("/{card_id}")
async def get_card(card_id: str):
    card = await asyncio.to_thread(cards_service.get_card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="card not found")
    return card.model_dump(mode="json")
