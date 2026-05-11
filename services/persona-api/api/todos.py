"""
Brief Todos API — surface the items extracted by brief_watcher to the
dashboard's Todos tab.

  GET    /api/todos/         — list this user's todos (open first, then done)
  PATCH  /api/todos/{id}     — toggle done / update title
  DELETE /api/todos/{id}     — remove permanently

All routes scope by Supabase user; the service-role client filters on
user_id explicitly so a token mix-up couldn't ever leak another user's
list.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import create_client

import config
from api.auth import get_current_user

router = APIRouter()


def _supabase():
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


class TodoUpdate(BaseModel):
    done: bool | None = None
    title: str | None = None


@router.get("/")
async def list_todos(user: dict = Depends(get_current_user)):
    """Return this user's todos, undone first then done, both newest first."""
    sb = _supabase()
    rows = (
        sb.table("brief_todos")
        .select("*")
        .eq("user_id", user["id"])
        .order("done")
        .order("created_at", desc=True)
        .execute()
    )
    return {"todos": rows.data or []}


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
