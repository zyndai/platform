"""
Memory API — surfaces the user's memory-layer assertion graph to the
dashboard's Memory settings page.

  GET  /api/memory/         — list all active assertions for this user
  POST /api/memory/confirm  — confirm a specific fact (predicate+object)
  POST /api/memory/forget   — forget a specific fact (predicate+object)

Assertions have no stable id in the memory-layer API — matching and
mutating is always by the (predicate, object) pair, which is why the
request bodies below take that instead of an id.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent.memory_client import confirm_by_ref, forget_by_ref, is_enabled, list_assertions
from api.auth import get_current_user

router = APIRouter()


class FactRefBody(BaseModel):
    predicate: str
    object: str


@router.get("/")
async def get_memory(user: dict = Depends(get_current_user)):
    """Return this user's full active assertion graph."""
    assertions = await list_assertions(user["id"])
    return {
        "enabled": is_enabled(),
        "count": len(assertions),
        "assertions": [asdict(a) for a in assertions],
    }


@router.post("/confirm")
async def confirm_memory_fact(body: FactRefBody, user: dict = Depends(get_current_user)):
    """Confirm a fact — the memory layer boosts its confidence to 0.97."""
    if not is_enabled():
        raise HTTPException(status_code=400, detail="Memory layer is not configured.")
    ok = await confirm_by_ref(user["id"], body.predicate, body.object)
    if not ok:
        raise HTTPException(status_code=502, detail="Couldn't confirm that fact.")
    return {"status": "confirmed"}


@router.post("/forget")
async def forget_memory_fact(body: FactRefBody, user: dict = Depends(get_current_user)):
    """Forget a fact — the memory layer soft-deletes it, never hard-deletes."""
    if not is_enabled():
        raise HTTPException(status_code=400, detail="Memory layer is not configured.")
    ok = await forget_by_ref(user["id"], body.predicate, body.object)
    if not ok:
        raise HTTPException(status_code=502, detail="Couldn't forget that fact.")
    return {"status": "forgotten"}
