"""
Brief API — creates and fetches the user's "My brief — for Aria" Google Doc.

The user's brief is a single Drive document Aria reads to stay current.
Created from S4 in onboarding (or the Settings → Accounts → Brief card).
Requires Google Drive + Docs scope (granted via the scoped OAuth flow with
features=docs).
"""

import logging
from typing import Optional

import requests as _req
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import create_client

import config
from api.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


BRIEF_DOC_TITLE = "My brief — for Aria"

# Per SCREENS.md S4. Plain text — Google Docs strips structure on bulk
# insert anyway, so we lean on em-dashes / blank lines for shape.
BRIEF_TEMPLATE = (
    "MY BRIEF — FOR ARIA\n"
    "\n"
    "Aria reads this to stay current on what you're up to. Edit anytime — she'll re-read whenever it changes.\n"
    "\n"
    "—\n"
    "\n"
    "What I'm working on\n"
    "—\n"
    "\n"
    "Who I'd like to meet\n"
    "—\n"
    "\n"
    "What I'm avoiding right now\n"
    "recruiters, fundraising calls, etc.\n"
    "\n"
    "Anything else Aria should know\n"
    "—\n"
)


class CreateBriefRequest(BaseModel):
    seed: Optional[str] = None  # optional one-line seed from S4


def _sb():
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def _read_user_metadata(user_id: str) -> dict:
    """Fetch fresh user_metadata from auth.users via the admin API."""
    url = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{user_id}"
    headers = {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
    }
    r = _req.get(url, headers=headers, timeout=10)
    if not r.ok:
        return {}
    return (r.json() or {}).get("user_metadata") or {}


def _patch_user_metadata(user_id: str, patch: dict) -> None:
    """Merge `patch` into auth.users.user_metadata via the admin API."""
    current = _read_user_metadata(user_id)
    merged = {**current, **patch}
    url = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{user_id}"
    headers = {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    r = _req.put(url, headers=headers, json={"user_metadata": merged}, timeout=10)
    if not r.ok:
        logger.warning(f"[brief] couldn't patch user_metadata: {r.status_code} {r.text[:200]}")


def _has_drive_scope(user_id: str) -> bool:
    """Check the api_tokens row for the Google connection — Drive scope
    appears as `documents`/`drive` in the saved scopes string."""
    try:
        sb = _sb()
        r = (
            sb.table("api_tokens")
            .select("scopes")
            .eq("user_id", user_id)
            .eq("provider", "google")
            .execute()
        )
        if not r.data:
            return False
        scopes = (r.data[0].get("scopes") or "").lower()
        return "documents" in scopes or "drive" in scopes
    except Exception as e:
        logger.warning(f"[brief] scope check failed: {e}")
        return False


@router.post("/create")
async def create_brief(req: CreateBriefRequest, user: dict = Depends(get_current_user)):
    """Create the user's brief Google Doc. Returns the doc URL.

    On missing Drive scope returns 403 with a `code` field the frontend
    uses to kick off the scoped OAuth flow."""
    if not _has_drive_scope(user["id"]):
        raise HTTPException(
            status_code=403,
            detail={"code": "drive_scope_needed",
                    "message": "I need Drive access to create the doc."},
        )

    # If the user already has a brief, just return it.
    meta = _read_user_metadata(user["id"])
    existing = meta.get("brief_doc")
    if isinstance(existing, dict) and existing.get("doc_id") and existing.get("url"):
        return {"status": "exists", **existing}

    try:
        from mcp.tools.google.docs import create_document, append_to_document

        created = create_document(user["id"], BRIEF_DOC_TITLE)
        if not created.get("success"):
            raise HTTPException(status_code=502, detail=created.get("error") or "Drive create failed")
        doc_id = created["document_id"]
        doc_url = created.get("link")

        body_text = BRIEF_TEMPLATE
        if req.seed and req.seed.strip():
            # Replace the first "What I'm working on / —" pair with the seed.
            body_text = body_text.replace(
                "What I'm working on\n—\n",
                f"What I'm working on\n{req.seed.strip()}\n",
                1,
            )
        appended = append_to_document(user["id"], doc_id, body_text)
        if not appended.get("success"):
            logger.warning(f"[brief] body insert failed: {appended.get('error')}")

        _patch_user_metadata(
            user["id"],
            {"brief_doc": {"doc_id": doc_id, "url": doc_url, "title": BRIEF_DOC_TITLE}},
        )

        return {"status": "created", "doc_id": doc_id, "url": doc_url, "title": BRIEF_DOC_TITLE}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[brief] create_brief crashed for {user['id']}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/me")
async def my_brief(user: dict = Depends(get_current_user)):
    """Return whatever brief metadata is on the user's auth row."""
    meta = _read_user_metadata(user["id"])
    brief = meta.get("brief_doc")
    if isinstance(brief, dict):
        return {"present": True, **brief}
    return {"present": False}
