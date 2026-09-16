import asyncio

from fastapi import APIRouter, Header, HTTPException, Query

from api.auth import verify_supabase_jwt
from models.card import AgentProfileCard
from services import cards as cards_service

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
    email = verify_supabase_jwt(authorization)
    if not email:
        raise HTTPException(status_code=401, detail="Unauthorized")
    result = await asyncio.to_thread(cards_service.get_card_by_owner, email)
    if not result:
        return None
    card, handle = result
    return {"card": card.model_dump(mode="json"), "handle": handle}


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
):
    email = verify_supabase_jwt(authorization)
    if not email:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        card = AgentProfileCard.model_validate(body)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid card data: {exc}") from exc
    ok = await asyncio.to_thread(cards_service.update_card, handle, card, email)
    if not ok:
        raise HTTPException(status_code=403, detail="Not the card owner")
    return card.model_dump(mode="json")


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
    email = verify_supabase_jwt(authorization)
    if not email:
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
    if stored_owner and stored_owner != email:
        raise HTTPException(status_code=403, detail="not the card owner")

    from services.zynd_memory import fetch_findability
    payload = fetch_findability(email)
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
