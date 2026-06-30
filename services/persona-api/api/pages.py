"""
Published pages API — create, list, delete for the owner, plus a public
read endpoint used by the Next.js page renderer.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import get_current_user
from services.page_publisher import (
    create_page,
    delete_page,
    get_page_public,
    list_pages,
    update_page,
)

router = APIRouter()


class CreatePageRequest(BaseModel):
    content: str = Field(..., min_length=1, description="HTML or Markdown body")
    title: str = Field(default="", max_length=200)
    format: str = Field(default="html", pattern=r"^(html|markdown|md|htm)$")
    visibility: str = Field(default="unlisted", pattern=r"^(public|unlisted|private)$")


class UpdatePageRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, max_length=200)
    format: str | None = Field(default=None, pattern=r"^(html|markdown|md|htm)$")
    visibility: str | None = Field(default=None, pattern=r"^(public|unlisted|private)$")


class CreatePageResponse(BaseModel):
    success: bool
    slug: str | None = None
    url: str | None = None
    title: str | None = None
    format: str | None = None
    visibility: str | None = None
    error: str | None = None


class PageListResponse(BaseModel):
    pages: list[dict[str, Any]]


class PublicPageResponse(BaseModel):
    slug: str
    url: str
    title: str
    format: str
    content: str
    created_at: str | None = None


class DeletePageResponse(BaseModel):
    success: bool
    slug: str | None = None
    error: str | None = None


@router.post("/", response_model=CreatePageResponse)
async def create_new_page(
    body: CreatePageRequest,
    user: dict = Depends(get_current_user),
):
    """Create a new shareable page."""
    result = create_page(
        user_id=user["id"],
        content=body.content,
        title=body.title,
        format=body.format,
        visibility=body.visibility,
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Bad request"))

    return CreatePageResponse(**result)


@router.get("/", response_model=PageListResponse)
async def list_user_pages(user: dict = Depends(get_current_user)):
    """Return all pages owned by the current user, newest first."""
    pages = list_pages(user_id=user["id"])
    return PageListResponse(pages=pages)


@router.patch("/{slug}", response_model=CreatePageResponse)
async def update_existing_page(
    slug: str,
    body: UpdatePageRequest,
    user: dict = Depends(get_current_user),
):
    """Update an existing page owned by the current user."""
    result = update_page(
        user_id=user["id"],
        slug=slug,
        content=body.content,
        title=body.title,
        format=body.format,
        visibility=body.visibility,
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Bad request"))

    return CreatePageResponse(**result)


@router.delete("/{slug}", response_model=DeletePageResponse)
async def remove_page(slug: str, user: dict = Depends(get_current_user)):
    """Delete a page owned by the current user."""
    result = delete_page(user_id=user["id"], slug=slug)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Bad request"))
    return DeletePageResponse(**result)


@router.get("/public/{slug}", response_model=PublicPageResponse)
async def get_public_page(slug: str):
    """Public read endpoint used by /pages/[slug] to render a shared page."""
    page = get_page_public(slug)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return PublicPageResponse(
        slug=page["slug"],
        url=page["url"],
        title=page["title"],
        format=page["format"],
        content=page["content"],
        created_at=page.get("created_at"),
    )
