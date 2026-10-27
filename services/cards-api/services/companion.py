"""Zynd Companion browser extension (docs/plans/ZYND_COMPANION_PLAN.md).

The extension holds a device token, not the person's website session. A token is minted
once, from a signed-in session (POST /cards/companion/pair), and only its SHA-256 is
stored. It is accepted by /cards/companion/* and nowhere else, and through it the
extension can change exactly two card fields: `working_on` and `exploring`.

Both writes go through cards.companion_save_fields, the same row-locked compare-and-swap
the card editor's section saves use. If the editor changed the same field in between,
the write is retried once on the fresh value.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from postgrest.exceptions import APIError

import config
from models.card import EXPLORING_KINDS, ExploringItem, _clean_exploring
from services import card_cache, owner_home
from services.card_view import cite_as
from services.signals import WORKING_ON_CAP
from services.zynd_memory import ping_revalidate

logger = logging.getLogger(__name__)

TOKEN_PREFIX = "zdc_"
TOKEN_IDLE_DAYS = 90             # a device unused this long must be paired again
MAX_DEVICES = 10                 # per person; pairing an eleventh revokes the least recently used
LAST_USED_REFRESH_MINUTES = 5    # how stale last_used_at may get before a request rewrites it
SAVE_ATTEMPTS = 2
PUBLIC_DEVICE_FIELDS = ("id", "label", "created_at", "last_used_at")

WORKING_ON_TEXT_MAX = 120
EXPLORING_MAX = 8                # stored per card
URL_MAX = 500
TITLE_MAX = 140
NOTE_MAX = 200
LABEL_MAX = 80

_TRACKING_PARAMS = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid", "ref_src", "ref_url",
                    "_hsenc", "_hsmi", "mkt_tok", "yclid", "twclid"}
# X and Twitter links carry a share-tracking query (?s=20&t=…) that identifies who shared them.
_NO_QUERY_HOSTS = {"x.com", "twitter.com", "mobile.twitter.com"}
_PRIVATE_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet", ".private")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SPACE = re.compile(r"\s+")


class CompanionError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


# ── Device tokens ────────────────────────────────────────────────────────────

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def clean_label(raw) -> str:
    label = _SPACE.sub(" ", _CONTROL.sub(" ", str(raw or ""))).strip()[:LABEL_MAX].strip()
    return label or "Browser"


def create_device(email: str, label) -> tuple[str, dict]:
    """Mint a device token for this owner. The token is returned once and never stored."""
    owner = email.strip().lower()
    sb = config.get_supabase()
    token = new_token()
    row = sb.table("companion_devices").insert(
        {"owner_email": owner, "token_hash": hash_token(token), "label": clean_label(label)}
    ).execute().data[0]
    live = [d for d in list_devices(owner) if d["id"] != row["id"]]
    for old in live[MAX_DEVICES - 1:]:        # list_devices is newest-used first
        revoke_device(owner, old["id"])
    return token, row


def list_devices(email: str) -> list[dict]:
    """The owner's live devices, most recently used first. Never includes a token or its hash."""
    rows = (config.get_supabase().table("companion_devices")
            .select(",".join(PUBLIC_DEVICE_FIELDS))
            .eq("owner_email", email.strip().lower()).is_("revoked_at", "null")
            .order("last_used_at", desc=True).execute().data or [])
    cutoff = _now() - timedelta(days=TOKEN_IDLE_DAYS)
    return [{k: r.get(k) for k in PUBLIC_DEVICE_FIELDS} for r in rows if (_parse(r["last_used_at"]) or cutoff) > cutoff]


def revoke_device(email: str, device_id: str) -> bool:
    rows = (config.get_supabase().table("companion_devices").update({"revoked_at": _now().isoformat()})
            .eq("id", device_id).eq("owner_email", email.strip().lower()).is_("revoked_at", "null")
            .execute().data or [])
    return bool(rows)


def device_for_token(token: str | None) -> dict | None:
    """The live device this token belongs to, or None (unknown, revoked or idle too long)."""
    if not token or not token.startswith(TOKEN_PREFIX) or len(token) > 200:
        return None
    sb = config.get_supabase()
    rows = sb.table("companion_devices").select("*").eq("token_hash", hash_token(token)).limit(1).execute().data or []
    if not rows or rows[0].get("revoked_at"):
        return None
    row = rows[0]
    now = _now()
    last = _parse(row.get("last_used_at")) or now
    if now - last > timedelta(days=TOKEN_IDLE_DAYS):
        return None
    if now - last > timedelta(minutes=LAST_USED_REFRESH_MINUTES):
        try:
            sb.table("companion_devices").update({"last_used_at": now.isoformat()}).eq("id", row["id"]).execute()
        except APIError:
            logger.warning("companion last_used_at not updated device=%s", row["id"])
    return row


# ── What may be clipped ──────────────────────────────────────────────────────

def clean_url(raw) -> str:
    """The public form of a link, or ValueError saying why it cannot go on a public card.

    A card is public, so a link to the person's own machine or an internal tool
    (localhost, a private address, an intranet name, a login in the URL) is refused here
    even though the extension refuses it too. Tracking parameters and the fragment go.
    """
    text = str(raw or "").strip()
    if not text or len(text) > URL_MAX:
        raise ValueError("That link is empty or too long")
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Only web links (http or https) can be added")
    if parts.username or parts.password or "@" in parts.netloc:
        raise ValueError("Links with a login in them cannot be added")
    host = parts.hostname.lower().rstrip(".")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if not address.is_global:
            raise ValueError("Private or local addresses cannot be added")
    elif "." not in host or host == "localhost" or host.endswith(_PRIVATE_SUFFIXES):
        raise ValueError("Pages on a private or local network cannot be added")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("That link has an invalid port") from exc
    netloc = host if address is None or address.version == 4 else f"[{host}]"
    if port and (parts.scheme, port) not in (("http", 80), ("https", 443)):
        netloc = f"{netloc}:{port}"
    if host.removeprefix("www.") in _NO_QUERY_HOSTS or host in _NO_QUERY_HOSTS:
        query = ""
    else:
        query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                           if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")])
    return urlunsplit((parts.scheme, netloc, parts.path or "/", query, ""))


def url_key(url: str) -> str:
    """Two spellings of one page compare equal: no www, no trailing slash, same query."""
    parts = urlsplit(url)
    host = (parts.hostname or "").removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}?{parts.query}"


def _text(raw, limit: int) -> str:
    return _SPACE.sub(" ", _CONTROL.sub(" ", str(raw or ""))).strip()[:limit].strip()


def build_item(url, title, kind, note, now: datetime | None = None) -> ExploringItem:
    clean = clean_url(url)
    kind = kind if kind in EXPLORING_KINDS else "link"
    host = (urlsplit(clean).hostname or "").removeprefix("www.")
    return ExploringItem(url=clean, title=_text(title, TITLE_MAX) or host, kind=kind,
                         note=_text(note, NOTE_MAX), added_at=(now or _now()).isoformat())


def add_exploring_item(current: list, item: ExploringItem) -> list[dict]:
    """`item` on top; an older entry for the same page is replaced, not duplicated."""
    key = url_key(item.url)
    kept = [c for c in current if isinstance(c, dict) and url_key(str(c.get("url") or "")) != key and c.get("url")]
    return [item.model_dump(mode="json"), *kept][:EXPLORING_MAX]


def remove_exploring_item(current: list, url: str) -> list[dict]:
    key = url_key(url)
    return [c for c in current if isinstance(c, dict) and url_key(str(c.get("url") or "")) != key]


def add_working_on_line(current: list, text) -> list[str]:
    line = _text(text, WORKING_ON_TEXT_MAX)
    if not line:
        raise ValueError("Write what you are working on")
    rest = [c for c in current if isinstance(c, str) and c.strip() and c.strip().lower() != line.lower()]
    return [line, *rest][:WORKING_ON_CAP]


def remove_working_on_line(current: list, text) -> list[str]:
    line = _text(text, WORKING_ON_TEXT_MAX).lower()
    return [c for c in current if isinstance(c, str) and c.strip().lower() != line]


# ── Writing to the card ──────────────────────────────────────────────────────

def _save_field(email: str, field: str, build) -> dict:
    """Apply build(current_list) to one card field atomically; returns the saved card JSON."""
    for attempt in range(SAVE_ATTEMPTS):
        row = owner_home.current_row(email)
        if not row:
            raise CompanionError(404, "Create your card first")
        stored = row["card"].get(field)
        current = stored if isinstance(stored, list) else []
        updated = build(current)
        if updated == current:
            return {**row["card"], "handle": row["handle"]}
        try:
            saved = config.get_supabase().rpc("companion_save_fields", {
                "p_email": email.strip().lower(), "p_handle": row["handle"],
                "p_patch": {field: updated}, "p_expected": {field: current},
            }).execute().data
        except APIError as exc:
            code = str(exc.code)
            if code == "40001" and attempt + 1 < SAVE_ATTEMPTS:
                continue
            if code == "40001":
                raise CompanionError(409, "Your card changed at the same moment. Try again.") from exc
            if code == "42501":
                raise CompanionError(403, "Not the card owner") from exc
            if code == "22023":
                raise CompanionError(422, "That could not be saved") from exc
            raise
        card_cache.invalidate()
        ping_revalidate(row["handle"])
        return saved
    raise CompanionError(409, "Your card changed at the same moment. Try again.")


def reembed(handle: str, saved: dict) -> None:
    """Working on feeds search, and its save cleared the vector; best-effort like the editor's save."""
    from models.card import AgentProfileCard
    from services.embed import card_search_text, embed_text
    try:
        vector = embed_text(card_search_text(AgentProfileCard.model_validate(saved)))
        (config.get_supabase().table("agent_profile_cards").update({"embedding": vector})
         .eq("handle", handle).eq("updated_at", saved["updated_at"]).execute())
        card_cache.invalidate()
    except Exception:
        logger.info("companion re-embed skipped handle=%s", handle)


def set_working_on(email: str, text) -> dict:
    return _save_field(email, "working_on", lambda cur: add_working_on_line(cur, text))


def drop_working_on(email: str, text) -> dict:
    return _save_field(email, "working_on", lambda cur: remove_working_on_line(cur, text))


def add_exploring(email: str, url, title, kind, note) -> dict:
    item = build_item(url, title, kind, note)
    return _save_field(email, "exploring", lambda cur: add_exploring_item(cur, item))


def drop_exploring(email: str, url) -> dict:
    return _save_field(email, "exploring", lambda cur: remove_exploring_item(cur, str(url or "")))


def lists_of(card: dict) -> dict:
    """The two lists as the extension shows them, from a saved card's JSON."""
    working = card.get("working_on")
    return {
        "working_on": [w for w in working if isinstance(w, str)] if isinstance(working, list) else [],
        "exploring": [i.model_dump(mode="json") for i in _clean_exploring(card.get("exploring"))],
    }


def profile(email: str) -> dict:
    """What the popup shows: who is paired and the two lists, as stored (not the public view)."""
    row = owner_home.current_row(email)
    if not row:
        raise CompanionError(404, "Create your card first")
    card = owner_home.card_from_row(row)
    return {
        "handle": card.handle,
        "name": card.identity.name,
        "headline": card.identity.headline,
        "avatar_url": card.identity.avatar_url or "",
        "card_url": cite_as(card.handle),
        "published": row["status"] == "published",
        "working_on": list(card.working_on),
        "exploring": [i.model_dump(mode="json") for i in card.exploring],
    }
