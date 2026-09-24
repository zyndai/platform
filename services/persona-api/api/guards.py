"""
Route guards — every route in this backend declares who may call it.

Before this module, 39 user-scoped routes (delete account, agent-send,
profile/brief writes, thread + meeting mutations, …) had no auth at all:
anyone who knew a user id could act as that user. See
ZYND_PLATFORM_LLD.md §3.1 for the full route table.

Vocabulary (each FastAPI dependency below is marked with
``__zynd_guard__`` so tests/test_route_guards.py can prove coverage):

  current_caller        any signed-in user, or a trusted internal service
  self_or_service(p)    path param ``p`` must be the caller's own user id,
                        or the caller is a trusted internal service
  self_only(p)          path param ``p`` must be the caller's own user id;
                        services are refused (e.g. account deletion)
  thread_participant    caller must be a side of dm_threads[thread_id]
  task_participant      caller must be a side of agent_tasks[task_id]
  @public               decorator for intentionally unauthenticated routes

Internal services (NOW, interim): memory-layer already calls these
routes with ``Authorization: Bearer <SUPABASE_SERVICE_KEY>``
(memory-layer/app/services/persona.py::_svc_headers). We accept that key —
and any key listed in INTERNAL_SERVICE_KEYS — as the "memory" service.
NEXT replaces this with per-service ``zsk_`` keys and explicit
``X-Zynd-User`` on-behalf-of (ZYND_PLATFORM_LLD.md §4.4).
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request

import config
from api.auth import get_current_user

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Caller:
    """Who is making the request.

    ``user_id`` is the user the request acts for: the signed-in user, or —
    for a service caller — the user named in the path / X-Zynd-User.
    """

    user_id: Optional[str]
    service: Optional[str] = None

    @property
    def is_service(self) -> bool:
        return self.service is not None


def _guard(fn):
    fn.__zynd_guard__ = True
    return fn


def public(fn):
    """Mark a route as intentionally unauthenticated (read by the coverage test)."""
    fn.__zynd_public__ = True
    return fn


def _bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    scheme, _, value = auth.partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


def _service_keys() -> list[str]:
    keys = [config.SUPABASE_SERVICE_KEY, *config.INTERNAL_SERVICE_KEYS]
    return [k for k in keys if k]


def _service_name(token: str) -> Optional[str]:
    if not token:
        return None
    for key in _service_keys():
        if hmac.compare_digest(token.encode(), key.encode()):
            return "memory"
    return None


@_guard
async def current_caller(request: Request) -> Caller:
    """A signed-in user (Supabase JWT) or a trusted internal service."""
    service = _service_name(_bearer(request))
    if service:
        return Caller(user_id=request.headers.get("X-Zynd-User") or None, service=service)
    user = await get_current_user(request)
    return Caller(user_id=user["id"])


def self_or_service(param: str = "user_id"):
    """The path param ``param`` must be the caller, unless a service calls."""

    @_guard
    async def dependency(request: Request, caller: Caller = Depends(current_caller)) -> Caller:
        target = request.path_params.get(param)
        if caller.is_service:
            logger.info("[guards] service=%s acting for user=%s on %s %s",
                        caller.service, target, request.method, request.url.path)
            return Caller(user_id=target, service=caller.service)
        if not target or caller.user_id != target:
            raise HTTPException(status_code=403, detail="Not your account")
        return caller

    return dependency


def self_only(param: str = "user_id", live: bool = False):
    """The path param must be the signed-in user; services are refused.

    ``live=True`` re-verifies the token with Supabase instead of trusting the
    60-second verification cache — used for destructive actions.
    """

    @_guard
    async def dependency(request: Request) -> Caller:
        token = _bearer(request)
        if not token:
            raise HTTPException(status_code=401, detail="Missing or invalid token")
        if _service_name(token):
            raise HTTPException(status_code=403, detail="Not allowed for services")
        if live:
            user_id = await _live_user_id(token)
        else:
            user_id = (await get_current_user(request))["id"]
        if user_id != request.path_params.get(param):
            raise HTTPException(status_code=403, detail="Not your account")
        return Caller(user_id=user_id)

    return dependency


async def _live_user_id(token: str) -> str:
    sb = config.get_supabase()
    try:
        resp = await asyncio.to_thread(sb.auth.get_user, token)
    except Exception:
        raise HTTPException(status_code=401, detail="Session could not be verified")
    if not resp or not resp.user:
        raise HTTPException(status_code=401, detail="Session could not be verified")
    return resp.user.id


def ensure_actor(caller: Caller, claimed_user_id: Optional[str]) -> None:
    """For request bodies that name the acting user (register, meetings, thread
    status/mode). A signed-in user may only act as themselves."""
    if caller.is_service:
        return
    if not claimed_user_id or caller.user_id != claimed_user_id:
        raise HTTPException(status_code=403, detail="Not your account")


async def _identities(user_id: str) -> set[str]:
    """The user's id plus their persona agent id — dm_threads stores either."""
    sb = config.get_supabase()
    rows = await asyncio.to_thread(
        lambda: sb.table("persona_agents").select("agent_id").eq("user_id", user_id).limit(1).execute().data
    )
    return {user_id, *(r["agent_id"] for r in rows or [] if r.get("agent_id"))}


async def assert_thread_participant(caller: Caller, thread_id: str) -> None:
    if caller.is_service:
        return
    sb = config.get_supabase()
    rows = await asyncio.to_thread(
        lambda: sb.table("dm_threads").select("initiator_id,receiver_id").eq("id", thread_id).limit(1).execute().data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Thread not found")
    sides = {rows[0].get("initiator_id"), rows[0].get("receiver_id")}
    if not sides & await _identities(caller.user_id):
        raise HTTPException(status_code=403, detail="Not a participant in this thread")


@_guard
async def thread_participant(thread_id: str, caller: Caller = Depends(current_caller)) -> Caller:
    await assert_thread_participant(caller, thread_id)
    return caller


@_guard
async def task_participant(task_id: str, caller: Caller = Depends(current_caller)) -> Caller:
    if caller.is_service:
        return caller
    sb = config.get_supabase()
    rows = await asyncio.to_thread(
        lambda: sb.table("agent_tasks").select("initiator_user_id,recipient_user_id")
        .eq("id", task_id).limit(1).execute().data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Task not found")
    if caller.user_id not in {rows[0].get("initiator_user_id"), rows[0].get("recipient_user_id")}:
        raise HTTPException(status_code=403, detail="Not a participant in this meeting")
    return caller
