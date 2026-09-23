"""
QuickEnrich client — the contact & company database behind the persona's
people-discovery tools.

Six endpoints are wrapped:

  POST /api/employees/contact-finder   → filterable people discovery (FREE)
  POST /api/companies/company-finder   → filterable company discovery (1 credit/company)
  GET  /api/employees/dataset-search   → all contacts at a domain, by title
  GET  /api/employees/search           → email for a known person
  GET  /api/employees/phone-search     → phone for a known person
  GET  /api/employees/email-search     → reverse lookup: email → person

This module is deliberately *synchronous*. MCP tools are executed via
``asyncio.to_thread(mcp_server._call, ...)`` (agent/orchestrator.py), so each
call already runs on a worker thread with no event loop to share — a sync
httpx client avoids the ``asyncio.run(...)`` wrapper that
``search_linkedin_people`` needs around services/linkedin_scraper.py.

Callers get the raw parsed payload back. Shaping into LLM-friendly results,
enum resolution, and caching all live one layer up (mcp/tools/quickenrich.py,
services/quickenrich_lookups.py, services/quickenrich_cache.py).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)


class QuickEnrichError(RuntimeError):
    """A QuickEnrich request failed. Carries the response body when there was one."""

    def __init__(self, message: str, *, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class QuickEnrichNotConfigured(QuickEnrichError):
    """QUICKENRICH_BASE_URL / QUICKENRICH_API_KEY are not set."""


class QuickEnrichValidationError(QuickEnrichError):
    """
    A 422 — one of the validated enum fields (country_code, industry,
    number_of_employees, revenue, services) wasn't an exact value from the
    lookup APIs. This is the expected failure mode when an LLM invents a
    filter value, so it gets its own type for the tool layer to handle.
    """


def _base_url() -> str:
    return (config.QUICKENRICH_BASE_URL or "").rstrip("/")


def is_configured() -> bool:
    """True when both a host and an API key are present."""
    return bool(_base_url() and config.QUICKENRICH_API_KEY)


def _auth_headers() -> dict:
    """
    Build the auth header. The header name is env-driven because the service's
    expected scheme is deployment-specific: "X-API-Key" sends the key raw,
    "Authorization" sends it as a Bearer token.
    """
    name = (config.QUICKENRICH_AUTH_HEADER or "X-API-Key").strip()
    key = config.QUICKENRICH_API_KEY
    value = f"Bearer {key}" if name.lower() == "authorization" else key
    return {name: value, "Accept": "application/json"}


def _request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
    require_key: bool = True,
) -> dict:
    """
    Issue one QuickEnrich request and return the parsed JSON body.

    Raises QuickEnrichNotConfigured / QuickEnrichValidationError /
    QuickEnrichError. Error bodies are logged rather than swallowed — the
    status line alone rarely says *which* filter value the API rejected, and
    losing that turns every failure into a manual reproduction (the same
    lesson services/linkedin_scraper.py learned with Apify).
    """
    base = _base_url()
    if not base:
        raise QuickEnrichNotConfigured("QUICKENRICH_BASE_URL is not configured")
    if require_key and not config.QUICKENRICH_API_KEY:
        raise QuickEnrichNotConfigured("QUICKENRICH_API_KEY is not configured")

    url = f"{base}/{path.lstrip('/')}"
    headers = _auth_headers() if require_key else {"Accept": "application/json"}

    try:
        with httpx.Client(timeout=config.QUICKENRICH_TIMEOUT) as client:
            resp = client.request(method, url, params=params, json=json, headers=headers)
    except httpx.HTTPError as e:
        raise QuickEnrichError(f"QuickEnrich request failed: {e}") from e

    if resp.status_code >= 400:
        body = resp.text[:1000]
        logger.error("[quickenrich] %s %s → %s: %s", method, path, resp.status_code, body)
        if resp.status_code == 422:
            raise QuickEnrichValidationError(
                "QuickEnrich rejected a filter value",
                status=422,
                body=body,
            )
        raise QuickEnrichError(
            f"QuickEnrich returned HTTP {resp.status_code}",
            status=resp.status_code,
            body=body,
        )

    try:
        payload = resp.json()
    except ValueError as e:
        raise QuickEnrichError("QuickEnrich returned a non-JSON response") from e

    return payload if isinstance(payload, dict) else {"data": payload}


# ── Lookups (public — no API key required) ───────────────────────────

def lookup(path: str, params: dict | None = None) -> Any:
    """
    Call one of the public /api/lookups/* endpoints. These need no API key and
    cost nothing, so they're safe to call speculatively for enum resolution.

    Returns whatever the endpoint returns — usually a list of strings, but
    company-services returns objects with usage counts.
    """
    payload = _request("GET", path, params=params, require_key=False)
    # Lookups return a bare list; _request wraps a bare list under "data".
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


# ── People ───────────────────────────────────────────────────────────

def contact_finder(body: dict) -> dict:
    """
    POST /api/employees/contact-finder — multi-filter people discovery.

    Free (credits_used: 0) and returns no email/phone values, only
    has_email/has_phone flags plus employee_linkedin. Rate limit 120/min.
    ``body`` is the already-assembled filter payload (include/exclude dicts).
    """
    return _request("POST", "/api/employees/contact-finder", json=body)


def dataset_search(
    company_url: str,
    *,
    title: str = "",
    page: int = 1,
    has_email: bool | None = None,
) -> dict:
    """
    GET /api/employees/dataset-search — every contact at a domain, optionally
    filtered by a title or comma-separated title list. Up to 20 per page.

    Charges 1 credit per returned contact that has an email or phone when a
    title is given; a flat 1 credit when it isn't.
    """
    params: dict = {"company_url": company_url, "page": page}
    if title:
        params["title"] = title
    if has_email is not None:
        params["has_email"] = str(bool(has_email)).lower()
    return _request("GET", "/api/employees/dataset-search", params=params)


def employee_search(
    *,
    linkedin_url: str = "",
    company_url: str = "",
    first_name: str = "",
    last_name: str = "",
) -> dict:
    """
    GET /api/employees/search — email for a known person.

    Provide either linkedin_url OR (company_url, first_name, last_name). When
    all four are given the API tries the LinkedIn URL first and falls back to
    verifying against the name + company.
    """
    params = _identity_params(linkedin_url, company_url, first_name, last_name)
    return _request("GET", "/api/employees/search", params=params)


def phone_search(
    *,
    linkedin_url: str = "",
    company_url: str = "",
    first_name: str = "",
    last_name: str = "",
) -> dict:
    """
    GET /api/employees/phone-search — phone for a known person. Same parameter
    shape as employee_search. One credit is charged only when a phone is found.
    """
    params = _identity_params(linkedin_url, company_url, first_name, last_name)
    return _request("GET", "/api/employees/phone-search", params=params)


def reverse_email_lookup(email: str) -> dict:
    """
    GET /api/employees/email-search — email address → the best matching person.
    One credit is charged only when a match is returned.
    """
    return _request("GET", "/api/employees/email-search", params={"email": email})


# ── Companies ────────────────────────────────────────────────────────

def company_finder(body: dict) -> dict:
    """
    POST /api/companies/company-finder — filterable company discovery.

    Charges 1 credit per company returned, which makes it the priciest
    endpoint here and the one whose results most benefit from caching.
    Rate limit 120/min.
    """
    return _request("POST", "/api/companies/company-finder", json=body)


# ── Helpers ──────────────────────────────────────────────────────────

def _identity_params(
    linkedin_url: str,
    company_url: str,
    first_name: str,
    last_name: str,
) -> dict:
    """
    Assemble the person-identity query params shared by the email and phone
    lookups, dropping empties so we never send blank exact-match filters.
    """
    params = {
        "linkedin_url": (linkedin_url or "").strip(),
        "company_url": (company_url or "").strip(),
        "first_name": (first_name or "").strip(),
        "last_name": (last_name or "").strip(),
    }
    return {k: v for k, v in params.items() if v}


def has_records(payload: dict) -> bool:
    """
    True when a response actually carried a record.

    A miss is a 200 with ``data: []`` and ``meta.reason`` set (EMAIL_NOT_FOUND,
    PHONE_NOT_FOUND, EMPLOYEE_NOT_FOUND) — not an error, and not charged. The
    single-record endpoints return a dict under ``data``; the search endpoints
    return a list.
    """
    data = payload.get("data")
    if isinstance(data, list):
        return len(data) > 0
    return bool(data)
