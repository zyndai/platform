"""S10 endpoints. Every owner read/write derives identity from the existing JWT."""
import asyncio
import html
import logging
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
from services.digest import valid_zone
from services.zynd_memory import ping_revalidate

router = APIRouter()
logger = logging.getLogger(__name__)


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
    # Optional so a client that predates the morning digest toggle can't switch it back on.
    morning_digest: bool | None = None


@router.patch("/mine/notification-prefs")
async def preferences(body: Preferences, authorization: str | None = Header(default=None)):
    email = email_for(authorization)
    prefs = body.model_dump(exclude_none=True)
    def save():
        sb = config.get_supabase()
        if "morning_digest" not in prefs:
            rows = sb.table("agent_profile_cards").select("notification_prefs").ilike("owner_email", cards._like_literal(email)).limit(1).execute().data or []
            stored = (rows[0].get("notification_prefs") or {}) if rows else {}
            prefs["morning_digest"] = stored.get("morning_digest", owner_home.DEFAULT_PREFS["morning_digest"])
        return sb.table("agent_profile_cards").update({"notification_prefs": prefs}).ilike("owner_email", cards._like_literal(email)).execute()
    await asyncio.to_thread(save)
    return prefs


class OwnerTimezone(BaseModel):
    timezone: str = Field(max_length=64)


@router.patch("/mine/timezone")
async def owner_timezone(body: OwnerTimezone, authorization: str | None = Header(default=None)):
    """The browser's IANA zone, so the morning digest arrives at 07:00 where the owner is."""
    email = email_for(authorization)
    zone = valid_zone(body.timezone)
    if zone is None:
        raise HTTPException(422, "Unknown timezone")
    def save():
        return config.get_supabase().table("agent_profile_cards").update({"timezone": zone.key}).ilike("owner_email", cards._like_literal(email)).execute()
    await asyncio.to_thread(save)
    return {"timezone": zone.key}


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


class BeaconRequest(BaseModel):
    text: str = Field(min_length=1, max_length=280)


@router.put("/by-handle/{handle}/beacon")
async def publish_beacon(handle: str, body: BeaconRequest, authorization: str | None = Header(default=None)):
    email = email_for(authorization)
    if not body.text.strip():
        raise HTTPException(422, "Write a short request before publishing")
    from services.beacons import save_beacon
    result = await asyncio.to_thread(save_beacon, handle, email, body.text)
    await asyncio.to_thread(ping_revalidate, handle)
    return {"beacon": result}


@router.delete("/by-handle/{handle}/beacon")
async def dismiss_beacon(handle: str, authorization: str | None = Header(default=None)):
    email = email_for(authorization)
    from services.beacons import save_beacon
    await asyncio.to_thread(save_beacon, handle, email, None)
    await asyncio.to_thread(ping_revalidate, handle)
    return Response(status_code=204)


SECTIONS = {
    "identity": {"identity"}, "summary": {"summary", "availability", "industries"},
    "signals": {"working_on", "connect_with", "love_talking_about", "can_help_with"},
    "skills": {"skills"}, "projects": {"projects"}, "career": {"work_experience"},
    "settings": {"calendly_url", "google_calendar_url"},
}


# The photo comes from the linked accounts (LinkedIn, X, GitHub), never from the
# editor, and the LinkedIn avatar self-heal moves it while the editor is open.
AVATAR_FIELDS = ("avatar_url", "avatar_bg_url")


def with_stored_photo(values: dict, stored_identity: dict) -> dict:
    """`values` with its identity photo fields taken from `stored_identity`.

    Whatever photo the editor sends back is just what it loaded, possibly stale.
    Using the stored one means a save can neither overwrite a self-healed photo nor
    conflict because of it, and the editor can't set a photo of its own.
    """
    identity = values.get("identity")
    if not isinstance(identity, dict):
        return values
    kept = {k: v for k, v in identity.items() if k not in AVATAR_FIELDS}
    photo = {f: stored_identity[f] for f in AVATAR_FIELDS if f in stored_identity}
    return {**values, "identity": {**kept, **photo}}


def without_blank_links(values: dict) -> dict:
    """The editor's form drops blank links, so it never holds the blank entries a
    stored card can carry. Compare without them, or such a card conflicts on every
    identity save."""
    identity = values.get("identity")
    if not isinstance(identity, dict) or not isinstance(identity.get("links"), dict):
        return values
    links = {k: v for k, v in identity["links"].items() if str(k).strip() and str(v).strip()}
    return {**values, "identity": {**identity, "links": links}}


def drifted_fields(visible: dict, acknowledged: dict) -> list[str]:
    """Names (never values) of the fields where the stored card moved off what the editor saw."""
    names = []
    for key, value in acknowledged.items():
        current = visible.get(key)
        if current == value:
            continue
        if isinstance(value, dict) and isinstance(current, dict):
            names += [f"{key}.{sub}" for sub in sorted(set(value) | set(current)) if value.get(sub) != current.get(sub)]
        else:
            names.append(key)
    return names


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
        visible = without_blank_links(cards._row_to_card(row).model_dump(mode="json"))
        # Sparse legacy JSON and cleaned work-history descriptions may differ
        # from the serialized editor model. Translate its acknowledged values
        # to raw JSON, then still compare under the SQL row lock.
        acknowledged = without_blank_links(with_stored_photo(body.expected, visible.get("identity") or {}))
        drift = drifted_fields(visible, acknowledged)
        if drift:
            logger.info("section conflict handle=%s section=%s fields=%s", handle, section, ",".join(drift))
            raise HTTPException(409, "Section changed in another session. Reload before saving.")
        patch = with_stored_photo(normalized, row["card"].get("identity") or {})
        return {key: row["card"].get(key, value) for key, value in acknowledged.items()}, patch
    expected, patch = await asyncio.to_thread(stored_expectations)
    result = await asyncio.to_thread(rpc, "s10_save_section", {"p_email": email, "p_handle": handle, "p_patch": patch, "p_expected": expected})
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
    sb.table("agent_profile_cards").update({"notification_prefs": {"weekly_digest": False, "email_nudges": False, "morning_digest": False}}).ilike("owner_email", cards._like_literal(rows[0]["owner_email"])).execute()
    return HTMLResponse('<!doctype html><title>Unsubscribed</title><h1>You are unsubscribed</h1><p>Your card stays available. You can change email preferences in your owner home.</p><a href="' + html.escape(config.SITE_BASE_URL.rstrip('/') + '/home', quote=True) + '">Owner home</a>', headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get("/mine/digest-preview")
async def digest_preview(authorization: str | None = Header(default=None)):
    from services.owner_notifications import render_weekly
    data = await owner_home.status(email_for(authorization), persist=False)
    if data is None:
        raise HTTPException(404, "Create your card first")
    body, markup = render_weekly(data, None)
    return {"body": body, "html": markup}
