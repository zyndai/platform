"""
Page Publisher — stores shareable HTML / Markdown pages created by the agent.

Pages are keyed by an unguessable slug and tied to the owning user. The
public-facing Next.js app renders them at:

    {PUBLIC_PAGE_BASE_URL}/pages/{slug}

This service uses the Supabase service-role client because it must create
rows from the MCP tool (which runs inside the Python process) and serve
public content without a user JWT.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any

import config

logger = logging.getLogger(__name__)

TABLE = "published_pages"
MAX_CONTENT_LENGTH = 1_000_000  # ~1 MB
MAX_TITLE_LENGTH = 200
VALID_FORMATS = {"html", "markdown"}
PUBLIC_VISIBILITIES = {"public", "unlisted"}


def _base_url() -> str:
    """Return the configured public base URL, falling back to the frontend URL."""
    url = getattr(config, "PUBLIC_PAGE_BASE_URL", None) or config.FRONTEND_URL
    return (url or "http://localhost:3000").rstrip("/")


def _supabase():
    return config.get_supabase()


def _normalize_format(fmt: str | None) -> str:
    fmt = (fmt or "html").lower().strip()
    if fmt in ("md", "markdown"):
        return "markdown"
    if fmt in ("html", "htm"):
        return "html"
    return "html"


def _normalize_visibility(visibility: str | None) -> str:
    v = (visibility or "unlisted").lower().strip()
    if v not in {"public", "unlisted", "private"}:
        v = "unlisted"
    return v


def _generate_slug() -> str:
    """Generate an unguessable URL-safe slug."""
    # 16 random bytes -> ~22 url-safe characters.
    return secrets.token_urlsafe(16)


def _page_url(slug: str) -> str:
    return f"{_base_url()}/pages/{slug}"


def create_page(
    user_id: str,
    content: str,
    title: str = "",
    format: str = "html",
    visibility: str = "unlisted",
) -> dict[str, Any]:
    """
    Create a new published page and return its public metadata.

    Args:
        user_id: Supabase user ID (injected by the orchestrator or API).
        content: Raw HTML or Markdown body.
        title: Optional page title.
        format: "html" or "markdown" (aliases like "md" are accepted).
        visibility: "unlisted" (default), "public", or "private".

    Returns:
        {"success": True, "slug", "url", "title", "format", "visibility"}
    """
    if not user_id:
        return {"success": False, "error": "user_id is required."}

    fmt = _normalize_format(format)
    vis = _normalize_visibility(visibility)

    if not isinstance(content, str):
        return {"success": False, "error": "content must be a string."}

    if len(content) > MAX_CONTENT_LENGTH:
        return {
            "success": False,
            "error": f"content is too long (max {MAX_CONTENT_LENGTH} characters).",
        }

    title = (title or "Untitled page").strip()
    if len(title) > MAX_TITLE_LENGTH:
        title = title[:MAX_TITLE_LENGTH].rstrip()

    sb = _supabase()

    # Retry a few times on the astronomically unlikely slug collision.
    for _ in range(5):
        slug = _generate_slug()
        try:
            row = (
                sb.table(TABLE)
                .insert(
                    {
                        "user_id": user_id,
                        "slug": slug,
                        "title": title,
                        "format": fmt,
                        "content": content,
                        "visibility": vis,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                .execute()
            )
            if row.data:
                return {
                    "success": True,
                    "slug": slug,
                    "url": _page_url(slug),
                    "title": title,
                    "format": fmt,
                    "visibility": vis,
                }
        except Exception as e:
            err = str(e).lower()
            if "unique" in err or "duplicate" in err:
                continue
            logger.exception("[page_publisher] create_page failed")
            return {"success": False, "error": f"Could not create page: {e}"}

    return {"success": False, "error": "Could not allocate a unique page slug — try again."}


def get_page_public(slug: str) -> dict[str, Any] | None:
    """
    Fetch a page for public viewing (used by the Next.js page renderer).

    Only pages whose visibility is public or unlisted are returned.
    """
    if not slug:
        return None

    sb = _supabase()
    try:
        result = sb.table(TABLE).select("*").eq("slug", slug).maybe_single().execute()
        row = result.data
        if not row:
            return None
        if row.get("visibility") not in PUBLIC_VISIBILITIES:
            return None
        return _serialize(row)
    except Exception as e:
        logger.warning(f"[page_publisher] get_page_public failed for {slug}: {e}")
        return None


def get_page_owned(user_id: str, slug: str) -> dict[str, Any] | None:
    """Fetch a page only if it belongs to the requesting user."""
    if not user_id or not slug:
        return None

    sb = _supabase()
    try:
        result = (
            sb.table(TABLE)
            .select("*")
            .eq("slug", slug)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        row = result.data
        return _serialize(row) if row else None
    except Exception as e:
        logger.warning(f"[page_publisher] get_page_owned failed for {slug}: {e}")
        return None


def list_pages(user_id: str) -> list[dict[str, Any]]:
    """Return all pages owned by the user, newest first."""
    if not user_id:
        return []

    sb = _supabase()
    try:
        result = (
            sb.table(TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [_serialize(row) for row in (result.data or [])]
    except Exception as e:
        logger.warning(f"[page_publisher] list_pages failed for {user_id}: {e}")
        return []


def update_page(
    user_id: str,
    slug: str,
    content: str | None = None,
    title: str | None = None,
    format: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    """Update a page if it belongs to the requesting user.

    Only the provided fields are changed; others are left untouched.
    """
    if not user_id or not slug:
        return {"success": False, "error": "user_id and slug are required."}

    updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}

    if content is not None:
        if len(content) > MAX_CONTENT_LENGTH:
            return {
                "success": False,
                "error": f"content is too long (max {MAX_CONTENT_LENGTH} characters).",
            }
        updates["content"] = content
    if title is not None:
        t = title.strip()
        if len(t) > MAX_TITLE_LENGTH:
            t = t[:MAX_TITLE_LENGTH].rstrip()
        updates["title"] = t
    if format is not None:
        updates["format"] = _normalize_format(format)
    if visibility is not None:
        updates["visibility"] = _normalize_visibility(visibility)

    if len(updates) == 1:
        return {"success": False, "error": "No fields provided to update."}

    sb = _supabase()
    try:
        result = (
            sb.table(TABLE)
            .update(updates)
            .eq("slug", slug)
            .eq("user_id", user_id)
            .execute()
        )
        row = result.data[0] if result.data else None
        if not row:
            return {"success": False, "error": "Page not found or not owned by you."}
        return {"success": True, **_serialize(row)}
    except Exception as e:
        logger.warning(f"[page_publisher] update_page failed for {slug}: {e}")
        return {"success": False, "error": f"Could not update page: {e}"}


def delete_page(user_id: str, slug: str) -> dict[str, Any]:
    """Delete a page if it belongs to the requesting user."""
    if not user_id or not slug:
        return {"success": False, "error": "user_id and slug are required."}

    sb = _supabase()
    try:
        # The query is scoped to user_id so this will silently no-op if the
        # page does not belong to the caller.
        sb.table(TABLE).delete().eq("slug", slug).eq("user_id", user_id).execute()
        return {"success": True, "slug": slug}
    except Exception as e:
        logger.warning(f"[page_publisher] delete_page failed for {slug}: {e}")
        return {"success": False, "error": f"Could not delete page: {e}"}


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a DB row into a clean dict for API responses."""
    slug = row["slug"]
    return {
        "slug": slug,
        "url": _page_url(slug),
        "title": row.get("title", ""),
        "format": row.get("format", "html"),
        "content": row.get("content", ""),
        "visibility": row.get("visibility", "unlisted"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
