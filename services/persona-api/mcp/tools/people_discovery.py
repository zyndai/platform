"""Read-only discovery across persona, published Cards, and external people."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

import requests

import config
from mcp.tools.quickenrich import search_people_database
from mcp.tools.zynd_network import search_zynd_personas


_FILTERS = frozenset({
    "titles", "exclude_titles", "company_names", "company_urls", "industries",
    "employee_ranges", "revenue_ranges", "countries", "cities", "localities",
    "company_keywords", "services",
})
_HANDLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def _public_url(value: object) -> str | None:
    if not isinstance(value, str) or not value or any(ord(c) < 33 for c in value):
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if parsed.scheme not in ("http", "https") or not host or parsed.username or parsed.password:
            return None
        if parsed.port is not None and parsed.port not in (80, 443):
            return None
        if host.lower() == "localhost" or host.lower().endswith((".localhost", ".local", ".internal")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if "." not in host or not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", host):
                return None
        if re.search(r"(?:^|/)(?:webhook|callback|a2a|api|internal)(?:/|$)", parsed.path, re.I):
            return None
    except ValueError:
        return None
    return value


def _public_text(value: object) -> str:
    """Do not forward operational URLs embedded in upstream descriptions."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"https?://[^\s<>\"']+", lambda m: m.group() if _public_url(m.group()) else "", value).strip()


def _group(status: str = "success", results: list | None = None, **extra) -> dict:
    results = results or []
    return {"status": status, "count": len(results), "results": results, **extra}


def _query_and_limit(query: str, limit: int) -> tuple[str, int] | None:
    if not isinstance(query, str) or not query.strip() or len(query.strip()) > 200:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
        return None
    return query.strip(), limit


def search_zynd_cards(query: str, limit: int = 8) -> dict:
    """Search claimed published Cards; a Card is not a messageable persona."""
    validated = _query_and_limit(query, limit)
    if not validated:
        return _group("error", error="A nonempty query (up to 200 characters) and limit 1-10 are required.")
    query, limit = validated
    try:
        response = requests.get(
            f"{getattr(config, 'CARDS_API_BASE_URL', 'https://api.zynd.ai').rstrip('/')}/v1/agents/search",
            params={"q": query, "limit": min(50, limit * 5), "include_unclaimed": "false"},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.exceptions.Timeout:
        return _group("timeout", error="Cards search timed out.")
    except (requests.exceptions.RequestException, ValueError):
        return _group("unavailable", error="Cards search is unavailable.")
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return _group("bad_response", error="Cards search returned an invalid response.")

    results = []
    seen = set()
    for row in payload["results"]:
        if not isinstance(row, dict) or row.get("claimed") is not True:
            continue
        handle = row.get("handle")
        if not isinstance(handle, str) or not _HANDLE.fullmatch(handle) or handle.lower() in seen:
            continue
        seen.add(handle.lower())
        results.append({
            "source_id": row.get("agent_id") if isinstance(row.get("agent_id"), str) else None,
            "handle": handle,
            "name": _public_text(row.get("name")),
            "headline": _public_text(row.get("headline")),
            "match_reasons": [
                {"type": _public_text(reason.get("type")), "text": _public_text(reason.get("text"))}
                if isinstance(reason, dict) else _public_text(reason)
                for reason in row.get("match_reasons", [])
                if isinstance(reason, (str, dict))
            ] if isinstance(row.get("match_reasons"), list) else [],
            "match_score": row.get("match_score") if isinstance(row.get("match_score"), (int, float)) else None,
            "location": _public_text(row.get("location")),
            "skills": [_public_text(skill) for skill in row.get("skills", []) if isinstance(skill, str)] if isinstance(row.get("skills"), list) else [],
            "public_url": f"https://cards.zynd.ai/p/{handle}",
            "connection_eligible": False,
        })
        if len(results) >= limit:
            break
    out = _group(results=results)
    if any(isinstance(row, dict) and row.get("claimed") is not True for row in payload["results"]):
        out["note"] = "Unclaimed profiles were excluded from the bounded search sample; this is not an exhaustive count of published Cards matches."
    return out


def discover_people(
    user_id: str, query: str, people_filters: dict = None,
    network_only: bool = False, limit: int = 8,
) -> dict:
    """Find people in independent sources without linking identities or revealing contacts.

    Args:
        user_id: Injected by the orchestrator; do not pass this yourself.
        query: Contextual topic, role, or interest to search across Zynd sources.
        people_filters: Targeting from known user goals/profile or explicit request.
            Supported list-of-string keys: titles, exclude_titles, company_names,
            company_urls, industries, employee_ranges, revenue_ranges, countries,
            cities, localities, company_keywords, services. Supply at least one
            positive criterion to check external prospects; never guess filters.
        network_only: Search only network personas, skipping Cards and external prospects.
        limit: Maximum results per source, from 1 to 10.
    """
    validated = _query_and_limit(query, limit)
    if not validated:
        return {"status": "error", "error": "A nonempty query (up to 200 characters) and limit 1-10 are required."}
    if people_filters is None:
        people_filters = {}
    if not isinstance(people_filters, dict) or set(people_filters) - _FILTERS:
        return {"status": "error", "error": "Unsupported people_filters; use only supported targeting dimensions."}
    if any(not isinstance(v, list) or not v or any(not isinstance(s, str) or not s.strip() for s in v)
           for v in people_filters.values()):
        return {"status": "error", "error": "Each people filter must be a nonempty list of nonempty strings."}
    if not isinstance(network_only, bool):
        return {"status": "error", "error": "network_only must be a boolean."}
    query, limit = validated

    try:
        raw = search_zynd_personas(query, top_k=limit, user_id=user_id)
        if not isinstance(raw, dict):
            network = _group("bad_response", error="Persona search returned an invalid response.")
        elif raw.get("status") != "success":
            network = _group(raw.get("status", "error"), error=raw.get("error_message") or raw.get("error") or "Persona search failed.")
        elif not isinstance(raw.get("results"), list):
            network = _group("bad_response", error="Persona search returned an invalid response.")
        else:
            people, seen = [], set()
            for row in raw["results"]:
                if not isinstance(row, dict) or not isinstance(row.get("agent_id"), str) or not row["agent_id"] or row["agent_id"] in seen:
                    continue
                seen.add(row["agent_id"])
                people.append({
                    "source_id": row["agent_id"],
                    "agent_id": row["agent_id"],
                    "name": _public_text(row.get("name")),
                    "description": _public_text(row.get("description")),
                    "match_reason": _public_text(row.get("match_reason")),
                    "match_score": row.get("match_score") if isinstance(row.get("match_score"), (int, float)) else None,
                    "public_url": _public_url(row.get("public_url")),
                    "connection_eligible": True,
                })
                if len(people) >= limit:
                    break
            network = _group(results=people)
    except Exception:
        network = _group("unavailable", error="Persona search is unavailable.")

    if network_only:
        cards = _group("skipped", reason="Restricted to network personas; card-only profiles were not checked.")
    else:
        try:
            cards = search_zynd_cards(query, limit=limit)
        except Exception:
            cards = _group("unavailable", error="Cards search is unavailable.")

    if network_only:
        external = _group("skipped", reason="Restricted to Zynd sources; external prospects were not checked.")
    elif not any(people_filters.get(key) for key in _FILTERS - {"exclude_titles"}):
        external = _group("needs_criteria", reason="Specify a title, company, industry, location, or other positive targeting criterion before checking external prospects.")
    else:
        try:
            raw = search_people_database(user_id, **people_filters, limit=limit)
            if not isinstance(raw, dict):
                external = _group("bad_response", error="External search returned an invalid response.")
            elif raw.get("status") != "success":
                external = _group(raw.get("status", "error"), error=raw.get("error_message") or raw.get("error") or "External search failed.",
                                  **{k: raw[k] for k in ("unresolved_filters", "normalized_filters", "hint") if k in raw})
            elif not isinstance(raw.get("results"), list):
                external = _group("bad_response", error="External search returned an invalid response.")
            else:
                people, seen = [], set()
                for row in raw["results"]:
                    if not isinstance(row, dict):
                        continue
                    link = _public_url(row.get("linkedin_url")) or _public_url(row.get("public_url"))
                    if link and link in seen:
                        continue
                    if link:
                        seen.add(link)
                    people.append({
                        "source_id": link,
                        "name": _public_text(row.get("name")),
                        "title": _public_text(row.get("title")),
                        "company_name": _public_text(row.get("company_name")),
                        "city": _public_text(row.get("city")),
                        "locality": _public_text(row.get("locality")),
                        "country": _public_text(row.get("country")),
                        "industry": _public_text(row.get("industry")),
                        "company_size": _public_text(row.get("company_size")),
                        "has_email": row.get("has_email") is True,
                        "has_phone": row.get("has_phone") is True,
                        "public_url": link,
                        "connection_eligible": False,
                    })
                    if len(people) >= limit:
                        break
                external = _group(results=people, **{k: raw[k] for k in ("total", "has_more", "normalized_filters", "unresolved_filters", "credits_used", "note") if k in raw})
        except Exception:
            external = _group("unavailable", error="External search is unavailable.")
    return {"zynd_network": network, "zynd_cards": cards, "external_prospects": external}
