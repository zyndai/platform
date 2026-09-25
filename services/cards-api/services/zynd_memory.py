"""Periodic refresh of card memory sections from the ZYND memory layer.

Service-to-service: the memory layer exposes /v1/service/findability/{email},
which requires MEMORY_SERVICE_TOKEN (shared secret). Only this backend — the
cron loop — ever fetches; anonymous card views read the stored snapshot on the
card row, so nothing is fetched per view and no private data ever leaves the
memory layer.
"""
import asyncio
import logging
from urllib.parse import quote

import httpx

import config

logger = logging.getLogger(__name__)


def fetch_findability(email: str) -> dict | None:
    """Fetch the memory layer's public findability card for an email.

    Returns the payload ({"connected": bool, "facts": [...]}) on success, or
    None on any failure (network, non-200, bad JSON). Never raises.
    """
    if not config.MEMORY_SERVICE_TOKEN or not (email or "").strip():
        return None
    url = config.MEMORY_LAYER_URL.rstrip("/") + "/v1/service/findability/" + quote(email.strip(), safe="")
    headers = {"Authorization": f"Bearer {config.MEMORY_SERVICE_TOKEN}"}
    try:
        resp = httpx.get(url, headers=headers, timeout=8)
    except Exception as exc:  # noqa: BLE001 — background cron: never raise, just log
        logger.warning("memory fetch failed email=%s err=%s", email, exc)
        return None
    if resp.status_code != 200:
        logger.warning("memory fetch non-200 email=%s status=%d", email, resp.status_code)
        return None
    try:
        return resp.json()
    except ValueError:
        logger.warning("memory fetch bad JSON email=%s", email)
        return None


async def refresh_all_cards_memory() -> dict:
    """One refresh cycle: for every published card with an owner_email, fetch
    the public findability card from the memory layer and store the snapshot.

    Best-effort per card: a failed fetch leaves the previous snapshot intact
    (never clobber good data with a transient outage). Returns run stats.
    """
    from services import cards as cards_service

    rows = cards_service.list_published_rows(columns="card,handle,owner_email")
    stats = {"total": len(rows), "updated": 0, "unchanged": 0,
             "no_email": 0, "not_connected": 0, "errors": 0}
    for row in rows:
        email = row.get("owner_email")
        if not (email or "").strip():
            stats["no_email"] += 1
            continue
        try:
            payload = await asyncio.to_thread(fetch_findability, email)
        except Exception as exc:  # noqa: BLE001 — one bad card must not kill the cycle
            logger.warning("memory fetch raised email=%s err=%s", email, exc)
            stats["errors"] += 1
            continue
        if payload is None:  # fetch failed — keep the previous snapshot
            stats["errors"] += 1
            continue
        facts = payload.get("facts") or None
        if facts is None:
            stats["not_connected"] += 1
            continue
        try:
            card = cards_service._row_to_card(row)
        except Exception as exc:  # noqa: BLE001
            logger.warning("card parse failed handle=%s err=%s", row.get("handle"), exc)
            stats["errors"] += 1
            continue
        if (card.zynd_memory or []) == facts:
            stats["unchanged"] += 1
            continue
        if cards_service.update_card_memory(row.get("handle"), facts):
            stats["updated"] += 1
        else:
            stats["errors"] += 1
    logger.info("memory refresh cycle: %s", stats)
    return stats


async def memory_refresh_loop() -> None:
    """Background loop: run one refresh cycle immediately, then every
    MEMORY_REFRESH_INTERVAL_HOURS. Failures are logged, never raised."""
    interval = max(1, config.MEMORY_REFRESH_INTERVAL_HOURS) * 3600
    logger.info("ZYND memory refresh loop started (every %ds)", interval)
    while True:
        try:
            await refresh_all_cards_memory()
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory refresh cycle failed: %s", exc)
        await asyncio.sleep(interval)
