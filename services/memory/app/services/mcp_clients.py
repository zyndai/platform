"""Per-assistant MCP clients (S09).

The JWT itself is not stored. ``jti`` is the revoke handle.
"""
from __future__ import annotations

import base64
import json

import asyncpg

from app.services.mcp_scopes import normalize_scopes


async def list_clients(pool: asyncpg.Pool, user_id: str) -> list[dict]:
    rows = await pool.fetch(
        """SELECT id, label, scopes, created_at, last_used_at
             FROM mcp_clients
            WHERE user_id = $1 AND revoked_at IS NULL
            ORDER BY created_at DESC""",
        user_id,
    )
    return [
        {
            "id": str(r["id"]),
            "label": r["label"],
            "scopes": list(r["scopes"] or []),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "last_used_at": r["last_used_at"].isoformat() if r["last_used_at"] else None,
        }
        for r in rows
    ]


async def revoke_client(pool: asyncpg.Pool, user_id: str, client_id: str) -> bool:
    status = await pool.execute(
        """UPDATE mcp_clients SET revoked_at = now()
            WHERE id = $1::uuid AND user_id = $2 AND revoked_at IS NULL""",
        client_id, user_id,
    )
    return status.endswith("1")


async def revoke_all_clients(pool: asyncpg.Pool, user_id: str) -> None:
    try:
        await pool.execute(
            """UPDATE mcp_clients SET revoked_at = now()
                WHERE user_id = $1 AND revoked_at IS NULL""",
            user_id,
        )
    except Exception:
        return


async def client_revoked(pool: asyncpg.Pool, jti: str) -> bool:
    """True when this jti is unknown or already revoked."""
    row = await pool.fetchrow(
        "SELECT revoked_at FROM mcp_clients WHERE jti = $1::uuid", jti,
    )
    return row is None or row["revoked_at"] is not None


async def touch_client(pool: asyncpg.Pool, jti: str) -> None:
    try:
        await pool.execute(
            "UPDATE mcp_clients SET last_used_at = now() WHERE jti = $1::uuid", jti,
        )
    except Exception:
        return


async def record_tool_call(pool: asyncpg.Pool, user_id: str | None, row: dict) -> None:
    try:
        await pool.execute(
            """INSERT INTO mcp_tool_calls (user_id, jti, tool, ok, ms, error_class)
               VALUES ($1, $2::uuid, $3, $4, $5, $6)""",
            user_id, row.get("jti"), row["tool"], row["ok"], row["ms"], row.get("error_class"),
        )
    except Exception:
        return


def connect_links(token: str, mcp_url: str) -> dict:
    """One-click targets. The JSON config is the fallback, not the primary path."""
    url = mcp_url.rstrip("/")
    remote = {"url": url, "headers": {"Authorization": f"Bearer {token}"}}
    encoded = base64.urlsafe_b64encode(json.dumps(remote).encode()).decode().rstrip("=")
    command = (
        f"claude mcp add --transport http zynd {url} "
        f"--header \"Authorization: Bearer {token}\""
    )
    config_json = json.dumps({"mcpServers": {"zynd": remote}}, indent=2)
    return {
        "cursor": f"cursor://anysphere.cursor-deeplink/mcp/install?name=zynd&config={encoded}",
        "claude_code": command,
        "server_url": url,
        "config_json": config_json,
    }


def clean_label(label: str | None) -> str:
    text = (label or "").strip()[:80]
    return text or "Assistant"


def clean_scopes(scopes: list[str] | None) -> list[str]:
    return normalize_scopes(scopes)
