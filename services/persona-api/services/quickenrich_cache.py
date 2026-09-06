"""
Supabase-backed cache for QuickEnrich records.

We cache *records*, not queries. Every QuickEnrich call upserts the people and
companies it returned; only the three deterministic person lookups (email,
phone, reverse-email) read the cache and skip the paid API call, because only
those are keyed lookups where a cached row is genuinely equivalent to a fresh
one. Search results are query-shaped and always re-run — but they still warm
this table, so a later reveal on someone from those results is free.

Rows are per-user (see db/patch_add_enriched_contacts.sql).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import config

logger = logging.getLogger(__name__)

CONTACTS_TABLE = "enriched_contacts"
COMPANIES_TABLE = "enriched_companies"

# QuickEnrich uses the literal string "N/A" for absent values rather than null.
_EMPTY = {"", "n/a", "na", "none", "null"}


def _sb():
    return config.get_supabase()


def _clean(value) -> str:
    """Normalize a QuickEnrich field, mapping its 'N/A' sentinel to empty."""
    text = str(value or "").strip()
    return "" if text.lower() in _EMPTY else text


# ── Key normalization ────────────────────────────────────────────────

def normalize_linkedin(url: str) -> str:
    """
    Reduce a LinkedIn profile URL to a stable path so the same person found
    via different links ('http://www.linkedin.com/in/x/', 'linkedin.com/in/x?tk=1')
    collapses onto one cache row.
    """
    raw = _clean(url).lower()
    if not raw:
        return ""
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    raw = raw.split("?", 1)[0].split("#", 1)[0]
    if raw.startswith("www."):
        raw = raw[4:]
    if raw.startswith("linkedin.com/"):
        raw = raw[len("linkedin.com/"):]
    return raw.strip("/")


def normalize_domain(url: str) -> str:
    """Reduce a company URL to a bare host, e.g. 'https://www.acme.com/x' → 'acme.com'."""
    raw = _clean(url).lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"//{raw}"
    host = urlparse(raw).netloc or ""
    if host.startswith("www."):
        host = host[4:]
    return host.strip("/")


def contact_key(
    *,
    linkedin_url: str = "",
    email: str = "",
    company_url: str = "",
    first_name: str = "",
    last_name: str = "",
) -> str:
    """
    Build the identity key for a person, preferring the most specific handle
    available. Returns "" when there's nothing stable to key on — callers
    treat that as "not cacheable" rather than inventing a key.
    """
    li = normalize_linkedin(linkedin_url)
    if li:
        return f"li:{li}"

    mail = _clean(email).lower()
    if mail:
        return f"em:{mail}"

    host = normalize_domain(company_url)
    first = _clean(first_name).lower()
    last = _clean(last_name).lower()
    if host and first and last:
        return f"nc:{host}|{first}|{last}"

    return ""


# ── Reads ────────────────────────────────────────────────────────────

def _is_fresh(row: dict) -> bool:
    """True when the row's paid enrichment is inside the TTL window."""
    stamp = row.get("enriched_at")
    if not stamp:
        return False
    try:
        enriched = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return False
    if enriched.tzinfo is None:
        enriched = enriched.replace(tzinfo=timezone.utc)
    ttl = timedelta(days=config.QUICKENRICH_CACHE_TTL_DAYS)
    return datetime.now(timezone.utc) - enriched < ttl


def get_contact(user_id: str, cache_key: str, *, require: str = "") -> dict | None:
    """
    Look up a cached contact.

    `require` names the field that must be present for this to count as a hit
    ("email" or "phone") — a row from a free discovery call has neither, and
    returning it would make the tool claim it found contact details it doesn't
    have. A hit also has to be inside the TTL window.
    """
    if not cache_key:
        return None
    try:
        result = (
            _sb().table(CONTACTS_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("cache_key", cache_key)
            .limit(1)
            .execute()
        )
    except Exception as e:
        # A cache miss is always safe to fall through on — never let a cache
        # problem take down the lookup itself.
        logger.warning("[quickenrich] cache read failed for %s: %s", cache_key, e)
        return None

    rows = result.data or []
    if not rows:
        return None

    row = rows[0]
    if require and not _clean(row.get(require)):
        return None
    if require and not _is_fresh(row):
        return None
    return row


def find_contact_by_email(user_id: str, email: str) -> dict | None:
    """Cached reverse lookup — email address → person row."""
    return get_contact(user_id, contact_key(email=email), require="email")


# ── Writes ───────────────────────────────────────────────────────────

def save_contact(user_id: str, record: dict, *, source: str, enriched: bool = False) -> str:
    """
    Upsert one QuickEnrich person record.

    `enriched` marks that this record carried paid contact details, which is
    what makes it eligible to serve a later reveal from cache. Returns the
    cache key, or "" when the record had nothing stable to key on.
    """
    key = contact_key(
        linkedin_url=record.get("employee_linkedin", ""),
        email=record.get("email", ""),
        company_url=record.get("company_url", ""),
        first_name=record.get("first_name", ""),
        last_name=record.get("last_name", ""),
    )
    if not key:
        return ""

    email = _clean(record.get("email"))
    phone = _clean(record.get("employee_phone"))

    row = {
        "user_id": user_id,
        "cache_key": key,
        "employee_linkedin": _clean(record.get("employee_linkedin")) or None,
        "email": email or None,
        "first_name": _clean(record.get("first_name")) or None,
        "last_name": _clean(record.get("last_name")) or None,
        "title": _clean(record.get("title")) or None,
        "company_name": _clean(record.get("company_name")) or None,
        "company_url": _clean(record.get("company_url")) or None,
        "phone": phone or None,
        "phone_type": _clean(record.get("employee_phone_type")) or None,
        # contact-finder reports these as booleans; the enrichment endpoints
        # don't send them at all, so infer from the values we actually got.
        "has_email": bool(record.get("has_email")) or bool(email),
        "has_phone": bool(record.get("has_phone")) or bool(phone),
        "data": record,
        "source": source,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if enriched and (email or phone):
        row["enriched_at"] = datetime.now(timezone.utc).isoformat()

    try:
        _sb().table(CONTACTS_TABLE).upsert(row, on_conflict="user_id,cache_key").execute()
    except Exception as e:
        logger.warning("[quickenrich] cache write failed for %s: %s", key, e)
        return ""
    return key


def save_contacts(user_id: str, records: list, *, source: str, enriched: bool = False) -> int:
    """Upsert a page of person records. Returns how many were cacheable."""
    saved = 0
    for record in records or []:
        if isinstance(record, dict) and save_contact(user_id, record, source=source, enriched=enriched):
            saved += 1
    return saved


def save_companies(user_id: str, records: list, *, source: str) -> int:
    """Upsert company records from company-finder."""
    saved = 0
    now = datetime.now(timezone.utc).isoformat()
    for record in records or []:
        if not isinstance(record, dict):
            continue
        key = normalize_domain(record.get("url") or record.get("company_url") or "")
        if not key:
            continue
        row = {
            "user_id": user_id,
            "cache_key": key,
            "company_name": _clean(record.get("company_name")) or None,
            "company_url": _clean(record.get("url") or record.get("company_url")) or None,
            "linkedin_url": _clean(record.get("linkedin_url")) or None,
            "industry": _clean(record.get("industry")) or None,
            "employee_count": _clean(record.get("employee_count")) or None,
            "revenue": _clean(record.get("revenue")) or None,
            "city": _clean(record.get("city")) or None,
            "region_code": _clean(record.get("region_code")) or None,
            "country_code": _clean(record.get("country_code")) or None,
            "data": record,
            "source": source,
            "updated_at": now,
        }
        try:
            _sb().table(COMPANIES_TABLE).upsert(row, on_conflict="user_id,cache_key").execute()
            saved += 1
        except Exception as e:
            logger.warning("[quickenrich] company cache write failed for %s: %s", key, e)
    return saved
