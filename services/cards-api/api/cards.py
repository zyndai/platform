import asyncio

from fastapi import APIRouter, HTTPException, Query

from services import cards as cards_service

router = APIRouter()


@router.get("")
async def search_cards(q: str = Query("", max_length=200)):
    if q:
        cards = cards_service.search_cards(q)
    else:
        cards = cards_service.list_published()
    return [c.model_dump(mode="json") for c in cards]


@router.get("/by-handle/{handle}")
async def get_card_by_handle(handle: str):
    card = await asyncio.to_thread(cards_service.get_card_by_handle, handle)
    if not card:
        raise HTTPException(status_code=404, detail="card not found")
    return card.model_dump(mode="json")


@router.get("/{card_id}")
async def get_card(card_id: str):
    card = await asyncio.to_thread(cards_service.get_card, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="card not found")
    return card.model_dump(mode="json")
