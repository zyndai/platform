"""Shareable page hosting — stores HTML / Markdown pages the GPT (or any MCP
client) creates on the user's behalf and serves them at a public link.

Ported from the agent-persona `page_publisher`, adapted to memory-layer's stack:
asyncpg (not Supabase) for storage, and server-side rendering (memory-layer has
no webapp) so a page is viewable directly at {public_base_url}/pages/{slug}.

Slugs are unguessable tokens. `unlisted` (the default) means anyone with the
link can view; `public` is the same for viewing but also listable; `private`
is owner-only and never served publicly.
"""
from __future__ import annotations

import html
import logging
import secrets
from typing import Any

import asyncpg

from app.config import settings

logger = logging.getLogger("zynd.pages")

MAX_CONTENT_LENGTH = 1_000_000  # ~1 MB
MAX_TITLE_LENGTH = 200
_PUBLIC_VISIBILITIES = {"public", "unlisted"}


def _base_url() -> str:
    return (settings.public_base_url or "http://localhost:8000").rstrip("/")


def _page_url(slug: str) -> str:
    return f"{_base_url()}/pages/{slug}"


def _normalize_format(fmt: str | None) -> str:
    fmt = (fmt or "html").lower().strip()
    if fmt in ("md", "markdown"):
        return "markdown"
    return "html"  # default + alias for htm/html/unknown


def _normalize_visibility(visibility: str | None) -> str:
    v = (visibility or "unlisted").lower().strip()
    return v if v in {"public", "unlisted", "private"} else "unlisted"


def _serialize(row: asyncpg.Record, include_content: bool = False) -> dict[str, Any]:
    out = {
        "slug": row["slug"],
        "url": _page_url(row["slug"]),
        "title": row["title"],
        "format": row["format"],
        "visibility": row["visibility"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }
    if include_content:
        out["content"] = row["content"]
    return out


async def create_page(
    pool: asyncpg.Pool,
    user_id: str,
    content: str,
    title: str = "",
    format: str = "html",
    visibility: str = "unlisted",
) -> dict[str, Any]:
    """Store a new page and return its public metadata (incl. the share `url`)."""
    if not isinstance(content, str) or not content.strip():
        return {"success": False, "error": "content must be a non-empty string."}
    if len(content) > MAX_CONTENT_LENGTH:
        return {"success": False, "error": f"content too long (max {MAX_CONTENT_LENGTH} chars)."}

    fmt = _normalize_format(format)
    vis = _normalize_visibility(visibility)
    title = (title or "Untitled page").strip()[:MAX_TITLE_LENGTH]

    # Retry on the astronomically unlikely slug collision (unique constraint).
    for _ in range(5):
        slug = secrets.token_urlsafe(16)
        try:
            row = await pool.fetchrow(
                """INSERT INTO published_pages (user_id, slug, title, format, content, visibility)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   RETURNING slug, title, format, visibility, created_at, updated_at""",
                user_id, slug, title, fmt, content, vis,
            )
            return {"success": True, **_serialize(row)}
        except asyncpg.UniqueViolationError:
            continue
        except Exception as exc:
            logger.exception("create_page failed for user %s", user_id)
            return {"success": False, "error": f"could not create page: {exc}"}
    return {"success": False, "error": "could not allocate a unique slug — try again."}


async def get_page_public(pool: asyncpg.Pool, slug: str) -> asyncpg.Record | None:
    """Fetch a page for public viewing — only if public or unlisted."""
    if not slug:
        return None
    row = await pool.fetchrow(
        "SELECT * FROM published_pages WHERE slug = $1", slug
    )
    if not row or row["visibility"] not in _PUBLIC_VISIBILITIES:
        return None
    return row


async def list_pages(pool: asyncpg.Pool, user_id: str) -> list[dict[str, Any]]:
    """All pages owned by the user, newest first (metadata only, no content)."""
    rows = await pool.fetch(
        """SELECT slug, title, format, visibility, created_at, updated_at
           FROM published_pages WHERE user_id = $1 ORDER BY created_at DESC""",
        user_id,
    )
    return [_serialize(r) for r in rows]


async def update_page(
    pool: asyncpg.Pool,
    user_id: str,
    slug: str,
    content: str | None = None,
    title: str | None = None,
    format: str | None = None,
    visibility: str | None = None,
) -> dict[str, Any]:
    """Update owner's page; only provided fields change."""
    if content is not None and len(content) > MAX_CONTENT_LENGTH:
        return {"success": False, "error": f"content too long (max {MAX_CONTENT_LENGTH} chars)."}

    sets: list[str] = ["updated_at = now()"]
    args: list[Any] = []
    if content is not None:
        args.append(content); sets.append(f"content = ${len(args)}")
    if title is not None:
        args.append(title.strip()[:MAX_TITLE_LENGTH]); sets.append(f"title = ${len(args)}")
    if format is not None:
        args.append(_normalize_format(format)); sets.append(f"format = ${len(args)}")
    if visibility is not None:
        args.append(_normalize_visibility(visibility)); sets.append(f"visibility = ${len(args)}")

    if not args:
        return {"success": False, "error": "no fields provided to update."}

    args.extend([slug, user_id])
    row = await pool.fetchrow(
        f"""UPDATE published_pages SET {', '.join(sets)}
            WHERE slug = ${len(args) - 1} AND user_id = ${len(args)}
            RETURNING slug, title, format, visibility, created_at, updated_at""",
        *args,
    )
    if not row:
        return {"success": False, "error": "page not found or not owned by you."}
    return {"success": True, **_serialize(row)}


async def delete_page(pool: asyncpg.Pool, user_id: str, slug: str) -> dict[str, Any]:
    """Delete owner's page. Scoped to user_id, so it no-ops on someone else's page."""
    result = await pool.execute(
        "DELETE FROM published_pages WHERE slug = $1 AND user_id = $2", slug, user_id
    )
    deleted = result.endswith("1")
    return {"success": deleted, "slug": slug} if deleted else {
        "success": False, "error": "page not found or not owned by you."
    }


# ── Server-side rendering ────────────────────────────────────────────────

_TEMPLATE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>%%TITLE%%</title>
<style>
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:#f7f8fa;color:#1a1a1e;
  font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:720px;margin:0 auto;padding:56px 24px 96px}
.card{background:#fff;border:1px solid #ececf1;border-radius:16px;padding:40px 44px;
  box-shadow:0 1px 3px rgba(0,0,0,.04)}
h1,h2,h3,h4{line-height:1.25;margin:1.6em 0 .5em;font-weight:650}
h1{font-size:1.9rem;margin-top:0}
h2{font-size:1.45rem}h3{font-size:1.2rem}
p{margin:0 0 1em}
a{color:#6d5efc;text-decoration:none}a:hover{text-decoration:underline}
img{max-width:100%;border-radius:10px}
pre{background:#0f1117;color:#e6e6ef;padding:16px 18px;border-radius:12px;overflow:auto;font-size:.9rem}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em}
:not(pre)>code{background:#f0f0f4;padding:.15em .4em;border-radius:6px}
blockquote{margin:1em 0;padding:.3em 1.1em;border-left:3px solid #6d5efc;color:#55555f}
table{border-collapse:collapse;width:100%;margin:1em 0}
th,td{border:1px solid #ececf1;padding:8px 12px;text-align:left}
th{background:#f7f7fb}
hr{border:none;border-top:1px solid #ececf1;margin:2em 0}
ul,ol{padding-left:1.4em}
.foot{max-width:720px;margin:0 auto;padding:20px 24px;color:#9a9aa6;font-size:.8rem;text-align:center}
.foot a{color:#9a9aa6}
</style></head>
<body><div class="wrap"><article class="card">%%BODY%%</article></div>
<div class="foot">Hosted on <a href="%%BASE%%">ZYND</a></div>
</body></html>"""


def render_page_html(row: asyncpg.Record) -> str:
    """Render a stored page row into a complete, styled HTML document.

    - markdown → converted to HTML then wrapped in the template.
    - html: a full document (starts with <!doctype/<html>) is served as-is;
      a fragment is wrapped in the template so it looks presentable.
    """
    fmt = row["format"]
    content = row["content"] or ""

    if fmt == "markdown":
        body = _markdown_to_html(content)
    else:
        stripped = content.lstrip().lower()
        if stripped.startswith("<!doctype") or stripped.startswith("<html"):
            return content  # author supplied a full page — respect it verbatim
        body = content

    return (
        _TEMPLATE
        .replace("%%TITLE%%", html.escape(row["title"] or "Untitled page"))
        .replace("%%BASE%%", _base_url())
        .replace("%%BODY%%", body)
    )


def _markdown_to_html(text: str) -> str:
    try:
        import markdown  # optional dep; only needed to render markdown pages
        return markdown.markdown(
            text, extensions=["fenced_code", "tables", "sane_lists", "nl2br"]
        )
    except ImportError:
        logger.warning("markdown package not installed — rendering as preformatted text")
        return f"<pre>{html.escape(text)}</pre>"
