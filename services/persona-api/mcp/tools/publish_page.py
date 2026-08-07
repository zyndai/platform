"""
Publish Page MCP tools — lets the agent save shareable HTML or Markdown
pages and list the pages the principal has already created.

These tools are principal-private; they are NOT exposed to foreign agents
in external mode.
"""

from __future__ import annotations

from typing import Any

from mcp.tools.error_utils import friendly_error
from services import page_publisher


def publish_page(
    user_id: str,
    content: str,
    title: str = "",
    format: str = "html",
    visibility: str = "unlisted",
) -> dict[str, Any]:
    """
    Publish a shareable HTML or Markdown page.

    Use this when the principal asks you to create a web page they can share,
    e.g. "make this into a page I can send to friends" or "publish this as
    HTML". The page is served publicly at the returned URL.

    Args:
        user_id: Injected automatically by the orchestrator.
        content: The page body. For `format="html"`, pass a complete HTML
            fragment or document. For `format="markdown"`, pass Markdown text.
        title: A short title for the page. Defaults to "Untitled page".
        format: "html" or "markdown". Aliases "md" / "htm" are accepted.
        visibility: "unlisted" (default — anyone with the link can view),
            "public", or "private" (owner-only).

    Returns:
        {"success": true, "slug", "url", "title", "format", "visibility"}
    """
    return page_publisher.create_page(
        user_id=user_id,
        content=content,
        title=title,
        format=format,
        visibility=visibility,
    )


def update_page(
    user_id: str,
    slug: str,
    content: str | None = None,
    title: str | None = None,
    format: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    """
    Update an existing shareable page.

    Use this when the principal asks to edit, change, or update a page they
    already published. You need the page's `slug` (or the slug at the end of
    the page URL). Only pass fields that should change.

    Args:
        user_id: Injected automatically by the orchestrator.
        slug: The page's unique slug, e.g. "abc123" from /pages/abc123.
        content: New HTML or Markdown body (optional).
        title: New title (optional).
        format: "html" or "markdown" (optional).
        visibility: "public", "unlisted", or "private" (optional).

    Returns:
        {"success": true, "slug", "url", "title", "format", "visibility"}
    """
    return page_publisher.update_page(
        user_id=user_id,
        slug=slug,
        content=content,
        title=title,
        format=format,
        visibility=visibility,
    )


def list_my_pages(user_id: str) -> dict[str, Any]:
    """
    List the shareable pages the principal has published.

    Use this when the principal asks "show my pages", "what pages have I
    made", or "list my published pages".

    Args:
        user_id: Injected automatically by the orchestrator.

    Returns:
        {"success": true, "pages": [{slug, url, title, format, visibility, created_at}]}
    """
    try:
        pages = page_publisher.list_pages(user_id=user_id)
        return {"success": True, "pages": pages, "count": len(pages)}
    except Exception as e:
        return friendly_error("list your published pages", e)
