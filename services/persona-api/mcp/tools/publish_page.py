"""
Publish Page MCP tools — lets the agent save shareable HTML or Markdown
pages and list the pages the principal has already created.

These tools are principal-private; they are NOT exposed to foreign agents
in external mode.
"""

from __future__ import annotations

from typing import Any

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
        return {"success": False, "error": str(e)}
