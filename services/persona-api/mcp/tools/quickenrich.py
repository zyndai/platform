"""
QuickEnrich MCP Tools — people & company discovery from a contact database.

Seven tools, registered in mcp/server.py:

  search_people_database     — filterable people discovery (FREE)
  search_companies_database  — filterable company discovery (1 credit/company)
  list_people_at_company     — every contact at a domain, by title
  get_email_for_person       — email for a known person (1 credit on a hit)
  get_phone_for_person       — phone for a known person (1 credit on a hit)
  identify_person_by_email   — reverse lookup: email → person (1 credit on a hit)
  list_people_filter_values  — the valid values for a filter dimension (FREE)

These are PRINCIPAL-PRIVATE. None of them belongs in the external-mode
allowlist in agent/orchestrator.py — a foreign agent must never be able to run
PII lookups through someone else's persona. The allowlist defaults to deny, so
this needs no code, only care when editing `_allowed_external_tools`.

Two notes on shape, both forced by the tool schema pipeline:

  * No dict parameters. ContextAware infers JSON Schema from annotations
    (contextaware/ContextAware.py) and `dict` becomes a property-less
    `object`, which strict function-calling backends reject. QuickEnrich's
    nested {include, exclude} filter shape is therefore flattened into paired
    flat list params here and reassembled before the call.
  * The LLM-facing description lives in mcp/server.py's `register(...)` call,
    not in these docstrings — ContextAware truncates docstrings at "Args:".
"""

from __future__ import annotations

from services import quickenrich as qe
from services import quickenrich_cache as cache
from services import quickenrich_lookups as lookups
from mcp.tools.error_utils import friendly_error, friendly_error_message

# Which flat tool params map onto which QuickEnrich filter dimension, and
# whether the values must be resolved against a lookup list first.
_PEOPLE_DIMENSIONS = {
    # tool param      → (api field,             lookup dimension or None)
    "titles":           ("title", None),
    "company_names":    ("company_name", None),
    "company_urls":     ("company_url", None),
    "cities":           ("city", None),
    "localities":       ("locality", None),
    "company_keywords": ("bio_li", None),
    "industries":       ("industry_linkedin", "industry"),
    "employee_ranges":  ("number_of_employees", "employee_range"),
    "revenue_ranges":   ("revenue", "revenue_range"),
    "countries":        ("country_code", "country_code"),
    "services":         ("services", "services"),
}

_COMPANY_DIMENSIONS = {
    "website_keywords":  ("home_page_text", None),
    "about_keywords":    ("bio_li", None),
    "company_names":     ("company_name", None),
    "cities":            ("city", None),
    "industries":        ("industry", "industry"),
    "employee_ranges":   ("number_of_employees", "employee_range"),
    "revenue_ranges":    ("revenue", "revenue_range"),
    "countries":         ("country_code", "country_code"),
    "services":          ("services", "services"),
}

_NOT_CONFIGURED = {
    "status": "error",
    "error": "The contact database isn't set up yet",
    "error_message": "QuickEnrich hasn't been configured for this deployment, so I can't search it.",
    "hint": "Ask an admin to set QUICKENRICH_BASE_URL and QUICKENRICH_API_KEY in the backend environment.",
    "results": [],
    "count": 0,
}


# ── Shared helpers ───────────────────────────────────────────────────

def _as_list(value) -> list[str]:
    """
    Coerce a tool argument into a clean list of strings.

    Models pass these as a JSON array most of the time, but a plain string or
    a comma-separated string often enough that normalizing here is cheaper
    than failing the call.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_as_list(item) if not isinstance(item, str) else ([item.strip()] if item.strip() else []))
        return out
    text = str(value).strip()
    return [text] if text else []


def _build_filters(spec: dict, supplied: dict, excludes: dict | None = None) -> tuple[dict, dict, list[dict]]:
    """
    Turn flat tool params into QuickEnrich's {include, exclude} filter body.

    Returns ``(body, normalized, unresolved)`` — `normalized` records any value
    we rewrote (e.g. "software" → "Computer Software") so the tool can tell the
    principal what it actually searched for, and `unresolved` carries values no
    lookup could match, with suggestions.
    """
    body: dict = {}
    normalized: dict = {}
    unresolved: list[dict] = []
    excludes = excludes or {}

    for param, (api_field, lookup_dim) in spec.items():
        include = _as_list(supplied.get(param))
        exclude = _as_list(excludes.get(param))
        if not include and not exclude:
            continue

        if lookup_dim:
            resolved_include, missed = lookups.resolve_many(lookup_dim, include)
            unresolved.extend(missed)
            if resolved_include != include:
                normalized[param] = resolved_include
            include = resolved_include

            if exclude:
                resolved_exclude, _ = lookups.resolve_many(lookup_dim, exclude)
                exclude = resolved_exclude

        if not include and not exclude:
            continue
        body[api_field] = {"include": include, "exclude": exclude}

    return body, normalized, unresolved


def _shape_person(record: dict) -> dict:
    """Flatten a QuickEnrich employee record into the compact result the LLM reads."""
    def field(key: str) -> str:
        text = str(record.get(key) or "").strip()
        # QuickEnrich writes the literal string "N/A" rather than null.
        return "" if text.upper() == "N/A" else text

    name = " ".join(part for part in (field("first_name"), field("last_name")) if part)
    email = field("email")
    phone = field("employee_phone")

    shaped = {
        "name": name,
        "first_name": field("first_name"),
        "last_name": field("last_name"),
        "title": field("title"),
        "linkedin_url": field("employee_linkedin"),
        "company_name": field("company_name"),
        "company_url": field("company_url"),
        "city": field("city"),
        "locality": field("locality"),
        "country": field("country_code"),
        # contact-finder sends these as booleans; the paid endpoints send the
        # values themselves and no flags — so derive from whichever we got.
        "has_email": bool(record.get("has_email")) or bool(email),
        "has_phone": bool(record.get("has_phone")) or bool(phone),
    }
    if email:
        shaped["email"] = email
    if phone:
        shaped["phone"] = phone
        if field("employee_phone_type"):
            shaped["phone_type"] = field("employee_phone_type")
    if field("industry"):
        shaped["industry"] = field("industry")
    if field("employee_count"):
        shaped["company_size"] = field("employee_count")
    return shaped


def _shape_company(record: dict) -> dict:
    """Flatten a QuickEnrich company record."""
    def field(key: str) -> str:
        text = str(record.get(key) or "").strip()
        return "" if text.upper() == "N/A" else text

    shaped = {
        "company_name": field("company_name"),
        "company_url": field("url") or field("company_url"),
        "linkedin_url": field("linkedin_url"),
        "industry": field("industry"),
        "employee_count": field("employee_count"),
        "revenue": field("revenue"),
        "city": field("city"),
        "region_code": field("region_code"),
        "country_code": field("country_code"),
        "phone": field("phone"),
        "email": field("home_page_email"),
    }
    services = record.get("services")
    if isinstance(services, list) and services:
        shaped["services"] = services[:12]
    snippet = field("home_page_text_snippet") or field("bio_li_snippet")
    if snippet:
        shaped["about"] = snippet[:400]
    return {k: v for k, v in shaped.items() if v}


def _validation_error(operation: str, exc: qe.QuickEnrichValidationError, unresolved: list[dict]) -> dict:
    """
    Turn a 422 into something the model can act on.

    A 422 means one of the validated enum fields wasn't an exact lookup value.
    Handing back the raw body would be useless, so surface the values we
    already know we couldn't resolve, and point at the tool that lists them.
    """
    return {
        "status": "error",
        "error": f"Couldn't {operation} — one of the filters isn't a valid value",
        "error_message": (
            "Industry, company size, revenue, country, and services have to match the "
            "database's own list exactly, and one of the values didn't."
        ),
        "hint": (
            "Call list_people_filter_values for the dimension in question to see the valid "
            "values, then retry with an exact one."
        ),
        "unresolved_filters": unresolved,
        "results": [],
        "count": 0,
    }


def _shape_cached(row: dict) -> dict:
    """
    Shape a cached row back into a result.

    The full API record is kept in `data`, so prefer that. Falling back to the
    row's own columns needs an alias: the table stores `phone`/`phone_type`
    where the API sends `employee_phone`/`employee_phone_type`, and shaping the
    row directly would silently drop the number.
    """
    record = row.get("data")
    if isinstance(record, dict) and record:
        return _shape_person(record)

    return _shape_person({
        **row,
        "employee_phone": row.get("phone"),
        "employee_phone_type": row.get("phone_type"),
    })


def _meta(payload: dict) -> dict:
    """Pull the credit/pagination block out of a response, tolerating its absence."""
    meta = payload.get("meta")
    return meta if isinstance(meta, dict) else {}


# ── Discovery ────────────────────────────────────────────────────────

def search_people_database(
    user_id: str,
    titles: list = None,
    exclude_titles: list = None,
    company_names: list = None,
    company_urls: list = None,
    industries: list = None,
    employee_ranges: list = None,
    revenue_ranges: list = None,
    countries: list = None,
    cities: list = None,
    localities: list = None,
    company_keywords: list = None,
    services: list = None,
    has_email: bool = False,
    has_phone: bool = False,
    limit: int = 10,
    page: int = 1,
) -> dict:
    """
    Search a contact database for people by role, company, industry, size,
    revenue, and location. Free — returns LinkedIn URLs, not email/phone.

    Args:
        user_id: Injected automatically by the orchestrator — do not pass it.
        titles: Job titles to match, e.g. ["VP of Engineering", "CTO"].
        exclude_titles: Job titles to rule out, e.g. ["Intern", "Assistant"].
        company_names: Company names to match.
        company_urls: Company domains to match, e.g. ["acme.com"].
        industries: Company industries. Must be exact — check with list_people_filter_values.
        employee_ranges: Company size labels like ["51-200"]. Must be exact.
        revenue_ranges: Company revenue labels like ["10M-50M"]. Must be exact.
        countries: ISO 2-letter country codes like ["US", "GB"]. Must be exact.
        cities: Company cities, e.g. ["San Francisco"].
        localities: The person's own metro area, e.g. ["San Francisco Bay Area"].
        company_keywords: Words to look for in the company's LinkedIn About text.
        services: Services the company offers. Must be exact.
        has_email: Only return people who have an email on file.
        has_phone: Only return people who have a phone on file.
        limit: How many people to return (1-100, default 10).
        page: Page number for paging through more results.

    Returns {status, count, results, total, has_more, normalized_filters,
    unresolved_filters}. Each result carries has_email/has_phone flags saying
    whether a paid reveal would succeed.
    """
    if not qe.is_configured():
        return dict(_NOT_CONFIGURED)

    supplied = {
        "titles": titles, "company_names": company_names, "company_urls": company_urls,
        "cities": cities, "localities": localities, "company_keywords": company_keywords,
        "industries": industries, "employee_ranges": employee_ranges,
        "revenue_ranges": revenue_ranges, "countries": countries, "services": services,
    }
    body, normalized, unresolved = _build_filters(
        _PEOPLE_DIMENSIONS, supplied, {"titles": exclude_titles}
    )

    if not body and not has_email and not has_phone:
        return {
            "status": "error",
            "error": "I need at least one filter to search",
            "error_message": (
                "A people search needs something to narrow on — a job title, company, "
                "industry, location, or company size."
            ),
            "hint": "Try again with at least a title or an industry, e.g. titles=[\"CTO\"].",
            "results": [],
            "count": 0,
        }

    body["per_page"] = max(1, min(int(limit or 10), 100))
    body["page"] = max(1, int(page or 1))
    if has_email:
        body["has_email"] = True
    if has_phone:
        body["has_phone"] = True

    try:
        payload = qe.contact_finder(body)
    except qe.QuickEnrichValidationError as e:
        return _validation_error("search the contact database", e, unresolved)
    except Exception as e:
        return friendly_error("search the contact database", e)

    records = payload.get("data") or []
    meta = _meta(payload)
    results = [_shape_person(r) for r in records if isinstance(r, dict)]

    # Warm the cache so a later email/phone reveal on one of these people is
    # a keyed hit. These records carry no contact values, so enriched=False.
    cache.save_contacts(user_id, records, source="contact-finder")

    out = {
        "status": "success",
        "count": len(results),
        "results": results,
        "total": meta.get("total", len(results)),
        "page": meta.get("page", body["page"]),
        "has_more": bool(meta.get("has_more")),
        "credits_used": meta.get("credits_used", 0),
        "source": "contact_database",
    }
    if normalized:
        out["normalized_filters"] = normalized
    if unresolved:
        out["unresolved_filters"] = unresolved
    if not results:
        out["note"] = (
            "No one in the database matched those filters. Loosening the narrowest "
            "filter (company size, revenue, or exact title) usually helps more than "
            "rephrasing."
        )
    return out


def search_companies_database(
    user_id: str,
    website_keywords: list = None,
    about_keywords: list = None,
    company_names: list = None,
    company_url: str = "",
    industries: list = None,
    employee_ranges: list = None,
    revenue_ranges: list = None,
    countries: list = None,
    cities: list = None,
    services: list = None,
    limit: int = 10,
    page: int = 1,
) -> dict:
    """
    Search a company database by what a company does, its industry, size,
    revenue, and location. Costs one credit per company returned.

    Args:
        user_id: Injected automatically by the orchestrator — do not pass it.
        website_keywords: Words to look for in the company's website copy.
        about_keywords: Words to look for in the company's LinkedIn About text.
        company_names: Company names to match.
        company_url: A single domain to look up, e.g. "acme.com".
        industries: Company industries. Must be exact — check with list_people_filter_values.
        employee_ranges: Company size labels like ["51-200"]. Must be exact.
        revenue_ranges: Company revenue labels like ["10M-50M"]. Must be exact.
        countries: ISO 2-letter country codes like ["US"]. Must be exact.
        cities: Company cities.
        services: Services the company offers. Must be exact.
        limit: How many companies to return (1-100, default 10). Each one costs a credit.
        page: Page number for paging through more results.

    Returns {status, count, results, total, has_more, credits_used}.
    """
    if not qe.is_configured():
        return dict(_NOT_CONFIGURED)

    supplied = {
        "website_keywords": website_keywords, "about_keywords": about_keywords,
        "company_names": company_names, "cities": cities, "industries": industries,
        "employee_ranges": employee_ranges, "revenue_ranges": revenue_ranges,
        "countries": countries, "services": services,
    }
    body, normalized, unresolved = _build_filters(_COMPANY_DIMENSIONS, supplied)

    domain = (company_url or "").strip()
    if domain:
        # company_url is a single string on this endpoint, not include/exclude.
        body["company_url"] = domain

    if not body:
        return {
            "status": "error",
            "error": "I need at least one filter to search",
            "error_message": "A company search needs something to narrow on — an industry, location, size, or what the company does.",
            "hint": "Try again with e.g. industries=[\"Computer Software\"] or website_keywords=[\"cloud migration\"].",
            "results": [],
            "count": 0,
        }

    body["per_page"] = max(1, min(int(limit or 10), 100))
    body["page"] = max(1, int(page or 1))

    try:
        payload = qe.company_finder(body)
    except qe.QuickEnrichValidationError as e:
        return _validation_error("search the company database", e, unresolved)
    except Exception as e:
        return friendly_error("search the company database", e)

    records = payload.get("data") or []
    meta = _meta(payload)
    cache.save_companies(user_id, records, source="company-finder")

    out = {
        "status": "success",
        "count": len(records),
        "results": [_shape_company(r) for r in records if isinstance(r, dict)],
        "total": meta.get("total", len(records)),
        "page": meta.get("page", body["page"]),
        "has_more": bool(meta.get("has_more")),
        "credits_used": meta.get("credits_used", 0),
        "source": "company_database",
    }
    if normalized:
        out["normalized_filters"] = normalized
    if unresolved:
        out["unresolved_filters"] = unresolved
    return out


def list_people_at_company(
    user_id: str,
    company_url: str,
    titles: str = "",
    only_with_email: bool = False,
    page: int = 1,
) -> dict:
    """
    List the people who work at one company, optionally narrowed to a set of
    job titles. Returns up to 20 per page, with email and phone included.

    Args:
        user_id: Injected automatically by the orchestrator — do not pass it.
        company_url: The company's domain or website, e.g. "acme.com".
        titles: One title or a comma-separated list, e.g. "CEO, CFO, Head of Sales".
        only_with_email: Only return people who have an email on file.
        page: Page number (20 contacts per page).

    Returns {status, count, results, total, has_more, credits_used}.
    """
    if not qe.is_configured():
        return dict(_NOT_CONFIGURED)

    domain = (company_url or "").strip()
    if not domain:
        return {
            "status": "error",
            "error": "I need a company website to look up",
            "error_message": "This searches one company at a time and needs its domain.",
            "hint": "Pass company_url, e.g. \"acme.com\". To find people across many companies, use search_people_database instead.",
            "results": [],
            "count": 0,
        }

    # `titles` is passed straight through: this endpoint takes a raw
    # comma-separated string and matches any of them, with no lookup list.
    title_arg = ", ".join(_as_list(titles))

    try:
        payload = qe.dataset_search(
            domain,
            title=title_arg,
            page=max(1, int(page or 1)),
            has_email=True if only_with_email else None,
        )
    except Exception as e:
        return friendly_error("look up people at that company", e)

    records = payload.get("data") or []
    meta = _meta(payload)
    # These records DO carry email/phone, so they count as enriched and can
    # serve a later reveal from cache.
    cache.save_contacts(user_id, records, source="dataset-search", enriched=True)

    out = {
        "status": "success",
        "count": len(records),
        "results": [_shape_person(r) for r in records if isinstance(r, dict)],
        "total": meta.get("total", len(records)),
        "page": meta.get("page", page),
        "has_more": meta.get("page", 1) < meta.get("last_page", 1),
        "credits_used": meta.get("credits_used", 0),
        "source": "contact_database",
    }
    if not records:
        out["note"] = f"No contacts on file at {domain}" + (f" with title matching \"{title_arg}\"." if title_arg else ".")
    return out


# ── Enrichment (paid, keyed lookups) ─────────────────────────────────

def _person_lookup(
    user_id: str,
    *,
    operation: str,
    require: str,
    fetcher,
    linkedin_url: str,
    company_url: str,
    first_name: str,
    last_name: str,
) -> dict:
    """
    Shared body of get_email_for_person / get_phone_for_person.

    Both take the same identity params, both check the cache before spending a
    credit, and both treat an empty `data` with a `reason` in meta as a clean
    "not found" rather than an error — QuickEnrich charges nothing for those.
    """
    if not qe.is_configured():
        return dict(_NOT_CONFIGURED)

    li = (linkedin_url or "").strip()
    co = (company_url or "").strip()
    first = (first_name or "").strip()
    last = (last_name or "").strip()

    if not li and not (co and first and last):
        return {
            "status": "error",
            "error": "I don't have enough to identify that person",
            "error_message": (
                "A lookup needs either their LinkedIn profile URL, or all three of "
                "company website, first name, and last name."
            ),
            "hint": "Find them with search_people_database first — its results include the LinkedIn URL you need here.",
        }

    key = cache.contact_key(
        linkedin_url=li, company_url=co, first_name=first, last_name=last
    )
    cached = cache.get_contact(user_id, key, require=require) if key else None
    if cached:
        return {
            "status": "success",
            "cached": True,
            "credits_used": 0,
            "person": _shape_cached(cached),
        }

    try:
        payload = fetcher(
            linkedin_url=li, company_url=co, first_name=first, last_name=last
        )
    except Exception as e:
        return friendly_error(operation, e)

    if not qe.has_records(payload):
        return {
            "status": "not_found",
            "credits_used": 0,
            "message": f"No {require} on file for that person — nothing was charged.",
            "hint": "The database simply doesn't have it. Reaching them through LinkedIn or their company's general contact page is the fallback.",
        }

    record = payload.get("data")
    if isinstance(record, list):
        record = record[0]

    cache.save_contact(user_id, record, source=operation, enriched=True)

    return {
        "status": "success",
        "cached": False,
        "credits_used": _meta(payload).get("credits_used", 1),
        "remaining_credits": _meta(payload).get("remaining_credits"),
        "person": _shape_person(record),
    }


def get_email_for_person(
    user_id: str,
    linkedin_url: str = "",
    company_url: str = "",
    first_name: str = "",
    last_name: str = "",
) -> dict:
    """
    Find the work email address for one specific person. Costs one credit when
    an email is found, nothing when it isn't.

    Args:
        user_id: Injected automatically by the orchestrator — do not pass it.
        linkedin_url: Their LinkedIn profile URL. The most reliable way to identify them.
        company_url: Their company's website — required if you have no LinkedIn URL.
        first_name: Their first name — required if you have no LinkedIn URL.
        last_name: Their last name — required if you have no LinkedIn URL.

    Returns {status, cached, credits_used, person} on a hit, or
    {status: "not_found"} when the database has no email for them.
    """
    return _person_lookup(
        user_id,
        operation="find an email for that person",
        require="email",
        fetcher=qe.employee_search,
        linkedin_url=linkedin_url,
        company_url=company_url,
        first_name=first_name,
        last_name=last_name,
    )


def get_phone_for_person(
    user_id: str,
    linkedin_url: str = "",
    company_url: str = "",
    first_name: str = "",
    last_name: str = "",
) -> dict:
    """
    Find the phone number for one specific person. Costs one credit when a
    number is found, nothing when it isn't.

    Args:
        user_id: Injected automatically by the orchestrator — do not pass it.
        linkedin_url: Their LinkedIn profile URL. The most reliable way to identify them.
        company_url: Their company's website — required if you have no LinkedIn URL.
        first_name: Their first name — required if you have no LinkedIn URL.
        last_name: Their last name — required if you have no LinkedIn URL.

    Returns {status, cached, credits_used, person} on a hit, or
    {status: "not_found"} when the database has no phone for them.
    """
    return _person_lookup(
        user_id,
        operation="find a phone number for that person",
        require="phone",
        fetcher=qe.phone_search,
        linkedin_url=linkedin_url,
        company_url=company_url,
        first_name=first_name,
        last_name=last_name,
    )


def identify_person_by_email(user_id: str, email: str) -> dict:
    """
    Look up who an email address belongs to — name, job title, company, and
    LinkedIn profile. Costs one credit when a match is found.

    Args:
        user_id: Injected automatically by the orchestrator — do not pass it.
        email: The email address to look up.

    Returns {status, cached, credits_used, person} on a hit, or
    {status: "not_found"} when nobody in the database has that address.
    """
    if not qe.is_configured():
        return dict(_NOT_CONFIGURED)

    address = (email or "").strip()
    if "@" not in address:
        return friendly_error_message(
            "look up that email address",
            "invalid email",
            hint="Pass a full email address, e.g. jane@acme.com.",
        )

    cached = cache.find_contact_by_email(user_id, address)
    if cached:
        return {
            "status": "success",
            "cached": True,
            "credits_used": 0,
            "person": _shape_cached(cached),
        }

    try:
        payload = qe.reverse_email_lookup(address)
    except Exception as e:
        return friendly_error("look up that email address", e)

    if not qe.has_records(payload):
        return {
            "status": "not_found",
            "credits_used": 0,
            "message": f"Nobody in the database matches {address} — nothing was charged.",
        }

    record = payload.get("data")
    if isinstance(record, list):
        record = record[0]

    cache.save_contact(user_id, record, source="email-search", enriched=True)

    return {
        "status": "success",
        "cached": False,
        "credits_used": _meta(payload).get("credits_used", 1),
        "remaining_credits": _meta(payload).get("remaining_credits"),
        "person": _shape_person(record),
    }


# ── Filter values ────────────────────────────────────────────────────

def list_people_filter_values(user_id: str, dimension: str, query: str = "", limit: int = 40) -> dict:
    """
    List the valid values for a filter dimension. Free.

    Args:
        user_id: Injected automatically by the orchestrator — do not pass it.
        dimension: One of "industry", "country_code", "employee_range",
            "revenue_range", or "services".
        query: Optional keyword to narrow the list — required in practice for
            "services", whose list is very long.
        limit: Maximum values to return (default 40).

    Returns {status, dimension, count, values}.
    """
    _ = user_id
    dim = (dimension or "").strip().lower()
    aliases = {
        "industries": "industry",
        "country": "country_code",
        "countries": "country_code",
        "employee_ranges": "employee_range",
        "company_size": "employee_range",
        "revenue_ranges": "revenue_range",
        "revenue": "revenue_range",
        "service": "services",
    }
    dim = aliases.get(dim, dim)

    if dim not in lookups.DIMENSIONS:
        return {
            "status": "error",
            "error": "That isn't a filter dimension I can list",
            "error_message": f"\"{dimension}\" isn't one of the dimensions with a fixed value list.",
            "hint": "Valid dimensions are: " + ", ".join(lookups.DIMENSIONS) + ".",
            "values": [],
            "count": 0,
        }

    try:
        values = lookups.allowed_values(dim, query=(query or "").strip())
    except Exception as e:
        return friendly_error("list the filter values", e)

    term = (query or "").strip().lower()
    if term and dim != "services":
        # The services endpoint already filters server-side; the cached lists
        # don't, so narrow them here.
        values = [v for v in values if term in v.lower()]

    capped = values[: max(1, int(limit or 40))]
    return {
        "status": "success",
        "dimension": dim,
        "count": len(capped),
        "total_available": len(values),
        "values": capped,
    }
