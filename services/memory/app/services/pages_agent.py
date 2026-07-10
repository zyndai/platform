
"""
Page Publisher (Supabase-backed) — writes to the same `published_pages` table
that the persona dashboard (https://persona.zynd.ai/dashboard/pages) reads from.

Adapted from agent-persona/backend/services/page_publisher.py.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from supabase import create_client, Client

from app.config import settings

logger = logging.getLogger(__name__)

TABLE = "published_pages"
MAX_CONTENT_LENGTH = 1_000_000
MAX_TITLE_LENGTH = 200
PUBLIC_VISIBILITIES = {"public", "unlisted"}

_supabase_client: Client | None = None


def _supabase() -> Client:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _supabase_client


def _base_url() -> str:
    url = settings.public_page_base_url or settings.public_base_url
    return (url or "http://localhost:8000").rstrip("/")


def _normalize_format(fmt: str | None) -> str:
    fmt = (fmt or "html").lower().strip()
    if fmt in ("md", "markdown"):
        return "markdown"
    return "html"


def _normalize_visibility(visibility: str | None) -> str:
    v = (visibility or "unlisted").lower().strip()
    return v if v in {"public", "unlisted", "private"} else "unlisted"


def _generate_slug() -> str:
    return secrets.token_urlsafe(16)


def _page_url(slug: str) -> str:
    return f"{_base_url()}/pages/{slug}"


async def create_page(user_id: str, content: str, title: str = "", format: str = "html",
                      visibility: str = "unlisted", expires_in_hours: int | None = None) -> dict[str, Any]:
    if not user_id:
        return {"success": False, "error": "user_id is required."}

    fmt = _normalize_format(format)
    vis = _normalize_visibility(visibility)

    if not isinstance(content, str):
        return {"success": False, "error": "content must be a string."}
    if len(content) > MAX_CONTENT_LENGTH:
        return {"success": False, "error": f"content is too long (max {MAX_CONTENT_LENGTH} characters)."}

    title = (title or "Untitled page").strip()
    if len(title) > MAX_TITLE_LENGTH:
        title = title[:MAX_TITLE_LENGTH].rstrip()

    now = datetime.now(timezone.utc)
    expires_at = None
    if expires_in_hours and expires_in_hours > 0:
        expires_at = (now + timedelta(hours=expires_in_hours)).isoformat()

    sb = _supabase()
    for _ in range(5):
        slug = _generate_slug()
        try:
            row = sb.table(TABLE).insert({
                "user_id": user_id, "slug": slug, "title": title,
                "format": fmt, "content": content, "visibility": vis,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "expires_at": expires_at,
            }).execute()
            if row.data:
                result: dict[str, Any] = {
                    "success": True, "slug": slug, "url": _page_url(slug),
                    "title": title, "format": fmt, "visibility": vis,
                }
                if expires_at:
                    result["expires_at"] = expires_at
                    result["note"] = f"Page expires in {expires_in_hours} hours."
                return result
        except Exception as e:
            err = str(e).lower()
            if "unique" in err or "duplicate" in err:
                continue
            return {"success": False, "error": f"Could not create page: {e}"}

    return {"success": False, "error": "Could not allocate a unique page slug — try again."}


def cleanup_expired_pages() -> int:
    """Delete all pages whose expires_at has passed. Returns count of deletions."""
    sb = _supabase()
    now = datetime.now(timezone.utc).isoformat()
    try:
        result = sb.table(TABLE).delete().not_.is_("expires_at", "null").lt("expires_at", now).execute()
        count = len(result.data) if result.data else 0
        if count:
            logger.info("cleanup_expired_pages: deleted %d expired anonymous pages from Supabase", count)
        return count
    except Exception as e:
        logger.warning("cleanup_expired_pages failed: %s", e)
        return 0


async def list_pages(user_id: str) -> list[dict[str, Any]]:
    if not user_id:
        return []
    sb = _supabase()
    try:
        result = sb.table(TABLE).select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        return [_serialize(row) for row in (result.data or [])]
    except Exception as e:
        logger.warning(f"[pages_agent] list_pages failed for {user_id}: {e}")
        return []


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    slug = row["slug"]
    item: dict[str, Any] = {
        "slug": slug, "url": _page_url(slug),
        "title": row.get("title", ""), "format": row.get("format", "html"),
        "visibility": row.get("visibility", "unlisted"),
        "created_at": row.get("created_at"), "updated_at": row.get("updated_at"),
    }
    if row.get("expires_at"):
        item["expires_at"] = row["expires_at"]
    return item
