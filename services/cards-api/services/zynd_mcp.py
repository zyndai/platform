"""Cards ↔ memory-layer bridge for fact review.

Service-to-service, MEMORY_SERVICE_TOKEN shared secret (same contract as
services/zynd_memory.py). cards-api vouches for the caller's identity after
verifying their Supabase session and proxies suggestion/approve/revoke calls;
memory owns the data. The cards MCP server and its token-mint path
(`connect_mcp_sync`) have been removed — no cards MCP token is minted anymore.
"""
import logging
from urllib.parse import quote

import httpx

import config

logger = logging.getLogger(__name__)


class MemoryUnavailable(Exception):
    """The memory layer could not be reached or returned an unexpected status."""


def _base() -> str:
    return config.MEMORY_LAYER_URL.rstrip("/")


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.MEMORY_SERVICE_TOKEN}",
            "Content-Type": "application/json"}


async def _request(method: str, path: str, json_body: dict | None = None,
                   params: dict | None = None) -> dict:
    """Call memory with the service token; raise MemoryUnavailable on failure."""
    url = _base() + path
    try:
        resp = await httpx.AsyncClient(timeout=10).request(
            method, url, json=json_body, params=params, headers=_headers(),
        )
    except httpx.HTTPError as exc:
        logger.warning("memory call failed %s %s: %s", method, path, exc)
        raise MemoryUnavailable("memory layer unreachable") from exc
    if resp.status_code >= 500:
        logger.warning("memory call non-2xx/5xx %s %s status=%d", method, path, resp.status_code)
        raise MemoryUnavailable("memory layer error")
    if resp.status_code >= 400:
        detail = None
        try:
            detail = resp.json().get("detail")
        except ValueError:
            pass
        raise MemoryUnavailable(detail or f"memory layer returned {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise MemoryUnavailable("memory layer returned invalid JSON") from exc


# ── Fact review (suggested → approved → public on the card) ──────────────────

async def suggested_facts(email: str) -> list[dict]:
    """Findability-eligible facts not yet public — review candidates for the card."""
    path = "/v1/service/suggestions/" + quote(email.strip().lower(), safe="")
    data = await _request("GET", path)
    return data.get("suggestions") or []


async def approve_fact(email: str, predicate: str, value: str) -> dict:
    return await _request("POST", "/v1/service/approve", {
        "email": email.strip().lower(), "predicate": predicate, "value": value,
    })


async def revoke_fact(email: str, predicate: str, value: str) -> dict:
    return await _request("POST", "/v1/service/revoke", {
        "email": email.strip().lower(), "predicate": predicate, "value": value,
    })
