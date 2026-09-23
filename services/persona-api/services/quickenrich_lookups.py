"""
QuickEnrich enum resolution.

Five QuickEnrich filter dimensions — country_code, industry, employee range,
revenue range, and services — 422 unless the string is byte-exact against the
service's own lookup lists. An LLM filling those filters will reliably emit
"Software" for "Computer Software", "50-200" for "51-200", or "USA" for "US",
so every value the model supplies is run through here first.

Resolution is exact → substring → close-match (difflib). Unresolved values are
reported back to the tool layer with suggestions rather than being dropped
silently, so the persona can say "'Fintech' isn't a valid industry — closest
are X and Y" instead of returning a confident empty result.

The lookup endpoints are public (no API key) and cheap, so the lists are
fetched lazily and held in a process-level TTL cache.
"""

from __future__ import annotations

import difflib
import logging
import threading
import time

from services.quickenrich import lookup as _lookup

logger = logging.getLogger(__name__)

# Lookup lists change rarely; six hours is plenty fresh and keeps a chatty
# session from re-fetching five lists on every search.
_TTL_SECONDS = 6 * 60 * 60

# dimension → lookup path. `services` is deliberately absent: its list is huge
# and the endpoint is a searchable autocomplete, so it resolves per-query below.
_PATHS = {
    "country_code": "/api/lookups/country-codes",
    "industry": "/api/lookups/industries",
    "employee_range": "/api/lookups/employee-ranges",
    "revenue_range": "/api/lookups/revenue-ranges",
}

DIMENSIONS = tuple(_PATHS) + ("services",)

_cache: dict[str, tuple[float, list[str]]] = {}
_lock = threading.Lock()


def _normalize(value: str) -> str:
    """Casefold and collapse separators so '51 - 200' matches '51-200'."""
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _coerce_names(raw) -> list[str]:
    """
    Lookup endpoints return either a bare list of strings or a list of objects
    (company-services returns names with usage counts). Flatten both.
    """
    names: list[str] = []
    for item in raw or []:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = item.get("name") or item.get("service") or item.get("value")
            if name:
                names.append(str(name))
    return names


def allowed_values(dimension: str, *, query: str = "") -> list[str]:
    """
    Return the valid values for a dimension.

    `services` is not cached wholesale — the list is long and the endpoint
    supports keyword search, so it's queried on demand. Everything else is
    fetched once per TTL window.
    """
    if dimension == "services":
        try:
            return _coerce_names(_lookup("/api/lookups/company-services", {"q": query} if query else None))
        except Exception as e:
            logger.warning("[quickenrich] services lookup failed: %s", e)
            return []

    path = _PATHS.get(dimension)
    if not path:
        return []

    now = time.time()
    with _lock:
        hit = _cache.get(dimension)
        if hit and now - hit[0] < _TTL_SECONDS:
            return hit[1]

    try:
        values = _coerce_names(_lookup(path))
    except Exception as e:
        # A dead lookup endpoint must not block the search itself — callers
        # fall back to passing the raw value through and letting the real API
        # 422 if it's wrong. A visible 422 beats a search that never runs.
        logger.warning("[quickenrich] %s lookup failed: %s", dimension, e)
        return []

    if values:
        with _lock:
            _cache[dimension] = (now, values)
    return values


def resolve(dimension: str, value: str) -> tuple[str | None, list[str]]:
    """
    Map one user/LLM-supplied value onto an exact allowed value.

    Returns ``(resolved, suggestions)``. On a miss, `resolved` is None and
    `suggestions` holds the nearest few valid values to show the user.
    """
    raw = (value or "").strip()
    if not raw:
        return None, []

    # For services, seed the candidate list with the value itself as a search
    # term so we're matching against the relevant slice, not the top-N global.
    options = allowed_values(dimension, query=raw if dimension == "services" else "")
    if not options:
        # Lookup unavailable — pass through unchanged rather than dropping the
        # filter. The API is the authority; let it reject if this is wrong.
        return raw, []

    norm_target = _normalize(raw)
    by_norm = {_normalize(o): o for o in options}

    if norm_target in by_norm:
        return by_norm[norm_target], []

    # Substring both ways: "software" → "Computer Software",
    # "Computer Software Inc" → "Computer Software".
    contains = [o for n, o in by_norm.items() if norm_target in n or n in norm_target]
    if len(contains) == 1:
        return contains[0], []
    if contains:
        # Ambiguous — prefer the shortest, which is the least-qualified match.
        return min(contains, key=len), []

    close = difflib.get_close_matches(norm_target, list(by_norm), n=3, cutoff=0.75)
    if close:
        return by_norm[close[0]], []

    suggestions = [by_norm[n] for n in difflib.get_close_matches(norm_target, list(by_norm), n=3, cutoff=0.4)]
    return None, suggestions


def resolve_many(dimension: str, values) -> tuple[list[str], list[dict]]:
    """
    Resolve a list of values for one dimension.

    Returns ``(resolved, unresolved)`` where each unresolved entry is
    ``{"dimension": ..., "value": ..., "suggestions": [...]}`` — shaped for
    handing straight back to the LLM so it can retry with a valid value or
    tell the principal what's actually available.
    """
    resolved: list[str] = []
    unresolved: list[dict] = []

    for value in values or []:
        hit, suggestions = resolve(dimension, value)
        if hit:
            if hit not in resolved:
                resolved.append(hit)
        else:
            unresolved.append({
                "dimension": dimension,
                "value": value,
                "suggestions": suggestions,
            })

    return resolved, unresolved


def clear_cache() -> None:
    """Drop the cached lookup lists. Used by tests."""
    with _lock:
        _cache.clear()
