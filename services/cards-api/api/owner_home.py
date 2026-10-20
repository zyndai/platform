"""S10 endpoints. Every owner read/write derives identity from the existing JWT."""
import asyncio
import html
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from postgrest.exceptions import APIError

import config
from api.mcp import _principal, _owner_email
from models.card import AgentProfileCard
from services import owner_home, cards
from services.zynd_memory import ping_revalidate

router = APIRouter()


def require_home():
    if not owner_home.enabled():
        raise HTTPException(404, "Owner home is not enabled")


def email_for(authorization):
    require_home()
    return _owner_email(_principal(authorization))


def rpc(name, params):
    try:
        return config.get_supabase().rpc(name, params).execute().data
    except APIError as exc:
        code = str(exc.code)
        raise HTTPException(409 if code == "40001" else 403 if code == "42501" else 422 if code == "22023" else 503,
                            "Section changed in another session. Reload before saving." if code == "40001" else
                            "Not the card owner" if code == "42501" else "Operation unavailable or invalid") from exc


@router.get("/mine/status")
async def mine_status(authorization: str | None = Header(default=None)):
    result = await owner_home.status(email_for(authorization))
    return Response(status_code=204) if result is None else result


@router.get("/mine/activity")
async def mine_activity(authorization: str | None = Header(default=None)):
    row = await asyncio.to_thread(owner_home.current_row, email_for(authorization))
    if not row:
        raise HTTPException(404, "Create your card first")
    return await asyncio.to_thread(owner_home.activity, row["handle"])


class Preferences(BaseModel):
    weekly_digest: bool
    email_nudges: bool


@router.patch("/mine/notification-prefs")
async def preferences(body: Preferences, authorization: str | None = Header(default=None)):
    email = email_for(authorization)
    def save():
        return config.get_supabase().table("agent_profile_cards").update({"notification_prefs": body.model_dump()}).ilike("owner_email", cards._like_literal(email)).execute()
    await asyncio.to_thread(save)
    return body.model_dump()


class Visibility(BaseModel):
    public: bool


@router.patch("/mine/visibility")
async def visibility(body: Visibility, authorization: str | None = Header(default=None)):
    email = email_for(authorization)
    row = await asyncio.to_thread(owner_home.current_row, email)
    if not row:
        raise HTTPException(404, "Create your card first")
    result = await asyncio.to_thread(rpc, "s10_visibility", {"p_email": email, "p_handle": row["handle"], "p_public": body.public})
    await asyncio.to_thread(ping_revalidate, row["handle"])
    return result


@router.post("/mine/nudges/{nudge_id}/dismiss")
async def dismiss(nudge_id: UUID, authorization: str | None = Header(default=None)):
    email = email_for(authorization)
    def save():
        return (config.get_supabase().table("card_nudges").update({"dismissed_at": datetime.now(timezone.utc).isoformat()})
                .eq("id", str(nudge_id)).eq("owner_email", email).execute())
    await asyncio.to_thread(save)
    return Response(status_code=204)


class Merge(BaseModel):
    canonical_id: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1, max_length=20)


@router.post("/merge")
async def merge(body: Merge, authorization: str | None = Header(default=None)):
    email = email_for(authorization)
    before = await asyncio.to_thread(owner_home.owner_rows, email)
    result = await asyncio.to_thread(rpc, "s10_merge", {"p_email": email, "p_canonical": body.canonical_id, "p_sources": list(set(body.source_ids))})
    for row in before:
        await asyncio.to_thread(ping_revalidate, row["handle"], alias=row.get("alias"))
    return result


class Section(BaseModel):
    patch: dict
    expected: dict


SECTIONS = {
    "identity": {"identity"}, "summary": {"summary", "availability", "industries"},
    "signals": {"working_on", "connect_with", "love_talking_about", "can_help_with"},
    "skills": {"skills"}, "projects": {"projects"}, "career": {"work_experience"},
    "settings": {"calendly_url", "google_calendar_url"},
}


# Photos are also written by the LinkedIn avatar self-heal, so the stored value
# can move while the editor is open.
AVATAR_FIELDS = ("avatar_url", "avatar_bg_url")


def expected_after_avatar_drift(patch: dict, expected: dict, visible: dict) -> dict:
    """Accept server-side drift in a photo field the owner is replacing.

    A photo the owner didn't touch still conflicts, so a save can't put a stale
    one back over the self-healed value.
    """
    new, old = patch.get("identity"), expected.get("identity")
    if not isinstance(new, dict) or not isinstance(old, dict):
        return expected
    current = visible.get("identity") or {}
    adopted = {**old, **{f: current.get(f) for f in AVATAR_FIELDS if new.get(f) != old.get(f)}}
    return {**expected, "identity": adopted}


@router.patch("/by-handle/{handle}/sections/{section}")
async def save_section(handle: str, section: str, body: Section, authorization: str | None = Header(default=None)):
    email = email_for(authorization)
    allowed = SECTIONS.get(section)
    if not allowed or not body.patch or not set(body.patch) <= allowed or set(body.expected) != set(body.patch):
        raise HTTPException(422, "Invalid section fields")
    # Validate/normalize editable fields, without accepting server-owned fields.
    try:
        model = AgentProfileCard.model_validate({"id": "validation", **body.patch})
    except ValueError as exc:
        raise HTTPException(422, "Invalid card data") from exc
    normalized = {key: model.model_dump(mode="json")[key] for key in body.patch}
    def stored_expectations():
        rows = (config.get_supabase().table("agent_profile_cards").select("card,handle")
                .eq("handle", handle).ilike("owner_email", cards._like_literal(email)).limit(1).execute().data or [])
        if not rows:
            raise HTTPException(403, "Not the card owner")
        row = rows[0]
        visible = cards._row_to_card(row).model_dump(mode="json")
        # Sparse legacy JSON and cleaned work-history descriptions may differ
        # from the serialized editor model. Translate its acknowledged values
        # to raw JSON, then still compare under the SQL row lock.
        acknowledged = expected_after_avatar_drift(body.patch, body.expected, visible)
        if any(visible.get(key) != value for key, value in acknowledged.items()):
            raise HTTPException(409, "Section changed in another session. Reload before saving.")
        return {key: row["card"].get(key, value) for key, value in acknowledged.items()}
    expected = await asyncio.to_thread(stored_expectations)
    result = await asyncio.to_thread(rpc, "s10_save_section", {"p_email": email, "p_handle": handle, "p_patch": normalized, "p_expected": expected})
    # The transaction clears the stale vector. FTS already reflects the saved
    # JSON. Best-effort regeneration is guarded against a newer section save.
    def reembed():
        from services.embed import embed_text, card_search_text
        try:
            vector = embed_text(card_search_text(AgentProfileCard.model_validate(result)))
            config.get_supabase().table("agent_profile_cards").update({"embedding": vector}).eq("handle", handle).eq("updated_at", result["updated_at"]).execute()
        except Exception:
            pass
    asyncio.create_task(asyncio.to_thread(reembed))
    await asyncio.to_thread(ping_revalidate, handle)
    return result


@router.get("/redirect/{handle}")
async def merged_redirect(handle: str):
    # Durable redirects survive disabling the home feature after rollout.
    target = await asyncio.to_thread(cards.merged_target, handle)
    return {"handle": target}


@router.get("/notifications/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe_confirmation(token: UUID):
    if config.SUPABASE_DB_SCHEMA != "cards":
        raise HTTPException(404, "Notifications unavailable")
    return HTMLResponse('<!doctype html><title>Unsubscribe from Zynd</title><h1>Email preferences</h1>'
                        '<p>Stop weekly digests and email nudges?</p><form method="post"><button>Unsubscribe</button></form>',
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.post("/notifications/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe(token: UUID):
    if config.SUPABASE_DB_SCHEMA != "cards":
        raise HTTPException(404, "Notifications unavailable")
    sb = config.get_supabase()
    rows = sb.table("agent_profile_cards").select("owner_email").eq("unsubscribe_token", str(token)).execute().data or []
    if not rows or not rows[0].get("owner_email"):
        raise HTTPException(404, "Link not found")
    sb.table("agent_profile_cards").update({"notification_prefs": {"weekly_digest": False, "email_nudges": False}}).ilike("owner_email", cards._like_literal(rows[0]["owner_email"])).execute()
    return HTMLResponse('<!doctype html><title>Unsubscribed</title><h1>You are unsubscribed</h1><p>Your card stays available. You can change email preferences in your owner home.</p><a href="' + html.escape(config.SITE_BASE_URL.rstrip('/') + '/home', quote=True) + '">Owner home</a>', headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get("/mine/digest-preview")
async def digest_preview(authorization: str | None = Header(default=None)):
    from services.owner_notifications import render_weekly
    data = await owner_home.status(email_for(authorization), persist=False)
    if data is None:
        raise HTTPException(404, "Create your card first")
    body, markup = render_weekly(data, None)
    return {"body": body, "html": markup}
