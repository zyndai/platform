"""
Brief Todos API — surface the items extracted by brief_watcher to the
dashboard's Todos tab.

  GET    /api/todos/         — list this user's todos (open first, then done)
  POST   /api/todos/extract  — force a brief re-read + LLM extraction now
  PATCH  /api/todos/{id}     — toggle done / update title
  DELETE /api/todos/{id}     — remove permanently

All routes scope by Supabase user; the service-role client filters on
user_id explicitly so a token mix-up couldn't ever leak another user's
list.
"""

from typing import Optional
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from postgrest.exceptions import APIError
from pydantic import BaseModel

import config
from api.auth import get_current_user

router = APIRouter()


def _supabase():
    return config.get_supabase()


def _is_missing_table(err: APIError) -> bool:
    return getattr(err, "code", None) == "PGRST205"


class TodoUpdate(BaseModel):
    done: Optional[bool] = None
    title: Optional[str] = None


@router.get("/")
async def list_todos(user: dict = Depends(get_current_user)):
    """Return this user's todos, undone first then done, both newest first."""
    sb = _supabase()
    try:
        rows = (
            sb.table("brief_todos")
            .select("*")
            .eq("user_id", user["id"])
            .order("done")
            .order("created_at", desc=True)
            .execute()
        )
    except APIError as e:
        if _is_missing_table(e):
            return {"todos": []}
        raise
    return {"todos": rows.data or []}


@router.post("/extract")
async def extract_todos_now(user: dict = Depends(get_current_user)):
    """
    Force an LLM extraction of todos from the user's current brief.

    The background brief_watcher only acts when the brief text hash
    changes — useful for normal edit-driven flow, but it means a user
    whose brief is unchanged never sees the extractor kick in on the
    current LLM-based code path. This endpoint runs the extractor
    inline so the Todos page's Refresh button always produces a
    meaningful result.
    """
    user_id = user["id"]

    def _run() -> dict:
        # Lazy imports — keep request-path imports cheap when the user
        # never hits this endpoint.
        from agent.persona_manager import get_persona_status
        from agent.brief_watcher import (
            extract_todo_titles,
            extract_todo_titles_llm,
        )

        persona = get_persona_status(user_id)
        if not persona.get("deployed"):
            raise HTTPException(status_code=404, detail="No active persona.")
        content = (persona.get("brief_content") or "").strip()
        if not content:
            raise HTTPException(
                status_code=400,
                detail="Your brief is empty — add some text first.",
            )

        titles = extract_todo_titles_llm(content)
        extractor = "llm"
        if titles is None:
            titles = extract_todo_titles(content)
            extractor = "regex_fallback"

        # Dedupe against existing OPEN rows the same way the watcher does
        # so this is idempotent — repeat clicks don't multiply todos.
        sb = _supabase()
        existing = (
            sb.table("brief_todos")
            .select("title")
            .eq("user_id", user_id)
            .eq("done", False)
            .execute()
        )
        have = {(r.get("title") or "").strip() for r in (existing.data or [])}
        new_titles = [t for t in titles if t and t not in have]
        if new_titles:
            sb.table("brief_todos").insert(
                [{"user_id": user_id, "title": t} for t in new_titles]
            ).execute()

        return {
            "status": "ok",
            "extractor": extractor,
            "extracted_total": len(titles),
            "inserted_new": len(new_titles),
        }

    return await asyncio.to_thread(_run)


@router.patch("/{todo_id}")
async def update_todo(
    todo_id: str,
    body: TodoUpdate,
    user: dict = Depends(get_current_user),
):
    """Toggle done state or rename a todo. Only fields supplied are touched."""
    sb = _supabase()
    patch: dict = {}
    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="title cannot be empty")
        patch["title"] = title
    if body.done is not None:
        patch["done"] = body.done
        patch["done_at"] = datetime.now(timezone.utc).isoformat() if body.done else None
    if not patch:
        raise HTTPException(status_code=400, detail="nothing to update")

    result = (
        sb.table("brief_todos")
        .update(patch)
        .eq("id", todo_id)
        .eq("user_id", user["id"])  # belt-and-suspenders ownership check
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="todo not found")
    return result.data[0]


@router.delete("/{todo_id}")
async def delete_todo(todo_id: str, user: dict = Depends(get_current_user)):
    """Delete a todo permanently."""
    sb = _supabase()
    sb.table("brief_todos").delete().eq("id", todo_id).eq("user_id", user["id"]).execute()
    return {"status": "deleted", "id": todo_id}
