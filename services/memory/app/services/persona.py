"""Client for the persona network backend (agent-persona, https://persona.zynd.ai).

ZYND consumes persona for identity (agent_id), social profile, connection requests,
messaging, and meetings. High-level persona endpoints take a user_id and sign with the
user's Ed25519 persona key SERVER-SIDE, so we authenticate service-to-service with the
Supabase service key and never handle keypairs here.

Contracts are from the API map of agent-persona/backend; verify against the live API
before the auth cutover. Every call is best-effort: network/HTTP errors raise
PersonaError so callers can degrade gracefully.
"""
import httpx

from app.config import settings


class PersonaError(RuntimeError):
    pass


def _svc_headers() -> dict:
    key = settings.supabase_service_key
    return {"Authorization": f"Bearer {key}", "apikey": key}


async def _persona(method: str, path: str, **kw) -> httpx.Response:
    url = settings.persona_base_url.rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            resp = await c.request(method, url, headers=_svc_headers(), **kw)
    except httpx.HTTPError as exc:
        raise PersonaError(f"persona {method} {path} failed: {exc}") from exc
    if resp.status_code >= 500:
        raise PersonaError(f"persona {method} {path} -> {resp.status_code}: {resp.text[:200]}")
    return resp


# ---- identity -------------------------------------------------------------

async def get_status(user_id: str) -> dict | None:
    """Full persona status (agent_id, name, profile w/ social links) or None if no persona."""
    resp = await _persona("GET", f"/api/persona/{user_id}/status")
    return resp.json() if resp.status_code == 200 else None


async def get_agent_id(user_id: str) -> str | None:
    status = await get_status(user_id)
    return status.get("agent_id") if status else None


async def ensure_persona(user_id: str, name: str = "", email: str = "") -> str | None:
    """Resolve the user's agent_id, registering a persona on first use (D2)."""
    agent_id = await get_agent_id(user_id)
    if agent_id:
        return agent_id
    resp = await _persona("POST", "/api/persona/register",
                          json={"user_id": user_id, "name": name or (email.split("@", 1)[0] if email else "ZYND user")})
    if resp.status_code in (200, 201):
        return resp.json().get("agent_id")
    raise PersonaError(f"persona register -> {resp.status_code}: {resp.text[:200]}")


# ---- social profile (point 2) --------------------------------------------

async def update_social(user_id: str, links: dict) -> None:
    """Set social URLs on the persona profile (linkedin/instagram/twitter/github/website)."""
    profile = {k: v for k, v in links.items() if v}
    resp = await _persona("PUT", f"/api/persona/{user_id}/profile", json={"profile": profile})
    if resp.status_code not in (200, 204):
        raise PersonaError(f"update profile -> {resp.status_code}: {resp.text[:200]}")


# ---- connect + message (point 3) -----------------------------------------

async def introduce(user_id: str, target_agent_id: str, target_name: str, message: str) -> dict:
    """Create a connection thread + send an intro message in one call."""
    resp = await _persona("POST", "/api/people/introductions",
                          json={"actor_user_id": user_id, "target_agent_id": target_agent_id,
                                "target_name": target_name, "message": message})
    if resp.status_code not in (200, 201):
        raise PersonaError(f"introduction -> {resp.status_code}: {resp.text[:200]}")
    return resp.json()


async def send_message(user_id: str, thread_id: str, content: str) -> dict:
    resp = await _persona("POST", f"/api/persona/{user_id}/agent-send",
                          json={"thread_id": thread_id, "content": content})
    if resp.status_code not in (200, 201):
        raise PersonaError(f"agent-send -> {resp.status_code}: {resp.text[:200]}")
    return resp.json()


# ---- connections + meetings (point 5) ------------------------------------

async def list_connections(agent_id: str) -> list[dict]:
    """Accepted connection threads for this agent (D3: via Supabase PostgREST + service key)."""
    url = settings.supabase_url.rstrip("/") + "/rest/v1/dm_threads"
    params = {"status": "eq.accepted",
              "or": f"(initiator_id.eq.{agent_id},receiver_id.eq.{agent_id})",
              "select": "id,initiator_id,receiver_id,status,updated_at"}
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            resp = await c.get(url, headers=_svc_headers(), params=params)
    except httpx.HTTPError as exc:
        raise PersonaError(f"list_connections failed: {exc}") from exc
    return resp.json() if resp.status_code == 200 else []


async def create_meeting(user_id: str, thread_id: str, payload: dict) -> dict:
    resp = await _persona("POST", "/api/meetings",
                          json={"thread_id": thread_id, "actor_user_id": user_id, "payload": payload})
    if resp.status_code not in (200, 201):
        raise PersonaError(f"create_meeting -> {resp.status_code}: {resp.text[:200]}")
    return resp.json()


async def pending_meetings(user_id: str) -> dict:
    resp = await _persona("GET", f"/api/meetings/pending/{user_id}")
    return resp.json() if resp.status_code == 200 else {"awaiting_me": [], "awaiting_them": []}
