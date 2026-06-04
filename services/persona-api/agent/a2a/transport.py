"""
A2A transport policy + dispatcher.

Picks the right A2A method (`message/send`, `message/stream`, push-mode
send-with-callback, `tasks/get`) based on the peer's advertised
capabilities and the caller's intent.

Decision rules — applied in order:

1. **Service-declared override.** If the peer's card sets
   ``x-zynd.requiresPushNotification = true``, the transport is forced
   to PUSH regardless of intent. Service authors set this to opt out
   of synchronous calls (e.g., human-in-the-loop services that always
   take longer than an HTTP timeout).

2. **Caller override.** ``TransportHints(force=...)`` lets the call
   site pin a transport — used when a tool wants to stream a long
   response or poll a task it already kicked off.

3. **Intent default.**

   - ``AGENT_TO_AGENT``: prefer PUSH (other persona may be in human
     mode, peer's user has to type a reply by hand). Fall back to
     SEND if the peer doesn't advertise ``capabilities.pushNotifications``.

   - ``SERVICE_CALL``: prefer SEND (services are fast and synchronous).
     Fall back to PUSH only when the service's card forced it via #1.

The dispatcher wraps :class:`agent.a2a.client.A2AClient`, adds peer-card
caching, and (for PUSH transport) registers an outbound-callback row so
the eventual push notification can be correlated back to the originating
conversation.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Optional, Protocol

from agent.a2a.client import A2AClient

logger = logging.getLogger(__name__)


# ── Enums ────────────────────────────────────────────────────────────


class Intent(str, Enum):
    """Why the caller is reaching out — drives the default transport."""

    #: Persona reaching out to another persona. Default to PUSH because
    #: the peer's user may be in human mode and slow to reply.
    AGENT_TO_AGENT = "agent_to_agent"

    #: Persona calling a service entity (zns:svc:…). Default to SEND
    #: because services are expected to respond quickly.
    SERVICE_CALL = "service_call"


class Transport(str, Enum):
    SEND = "send"
    STREAM = "stream"
    PUSH = "push"
    GET = "get"


# ── Hints / result types ─────────────────────────────────────────────


@dataclass
class TransportHints:
    """Caller-side overrides for the policy decision."""

    force: Optional[Transport] = None
    """Pin the transport regardless of intent or peer capabilities. Use
    sparingly — the intent default is usually correct."""


@dataclass
class DispatchResult:
    """What the dispatcher returns to the caller after a send.

    Exactly one of ``task`` or ``stream`` is populated for non-PUSH
    transports. PUSH always populates ``task`` (the receiver's initial
    Task ack) and additionally ``callback_id`` so the caller can
    correlate the eventual push payload back.
    """

    transport: Transport
    task: Optional[dict[str, Any]] = None
    stream: Optional[Any] = None  # AsyncIterator[dict] — typed loosely to keep import surface small
    callback_id: Optional[str] = None
    push_url: Optional[str] = None
    push_token: Optional[str] = None


# ── Card cache ────────────────────────────────────────────────────────

# Module-level peer-card cache. 5-min TTL keeps verification + transport
# decisions cheap on repeat sends without going stale during a long
# session. Purely best-effort — failures don't poison the cache.
_CARD_CACHE_TTL_SEC = 300
_card_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_card_cache_lock = asyncio.Lock()


async def _fetch_peer_card_cached(client: A2AClient, card_url: str) -> Optional[dict[str, Any]]:
    now = time.time()
    async with _card_cache_lock:
        hit = _card_cache.get(card_url)
        if hit and (now - hit[0]) < _CARD_CACHE_TTL_SEC:
            return hit[1]
    try:
        card = await client.fetch_card(card_url)
    except Exception as e:  # noqa: BLE001 — best effort
        logger.warning("transport.fetch_peer_card failed for %s: %s", card_url, e)
        return None
    async with _card_cache_lock:
        _card_cache[card_url] = (now, card)
    return card


def _is_deferred_push_ack(task: dict[str, Any]) -> bool:
    """True when the immediate response is a push-deferral ack rather than
    the real result. Indicators: any artifact part has delivery='push', or
    all artifact data parts have a null/empty shortlist alongside a taskId."""
    for art in task.get("artifacts") or []:
        for part in art.get("parts") or []:
            if not isinstance(part, dict):
                continue
            if part.get("kind") == "data":
                data = part.get("data") or {}
                if data.get("delivery") == "push":
                    return True
                if data.get("taskId") and not data.get("shortlist"):
                    return True
    return False


def _extract_reply_text_from_task(task: dict[str, Any]) -> Optional[str]:
    """Best-effort: pull readable reply text from an A2A Task — first
    `status.message.parts`, then the first artifact's parts. Returns
    None when neither is populated."""
    if not isinstance(task, dict):
        return None
    status = task.get("status") or {}
    msg = status.get("message")
    if isinstance(msg, dict):
        chunks = _join_text_parts(msg.get("parts"))
        if chunks:
            return chunks
    for art in task.get("artifacts") or []:
        if not isinstance(art, dict):
            continue
        chunks = _join_text_parts(art.get("parts"))
        if chunks:
            return chunks
    return None


def _join_text_parts(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    out: list[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("kind") == "text":
            t = p.get("text")
            if isinstance(t, str) and t:
                out.append(t)
    return "\n".join(out)


def invalidate_card_cache(card_url: Optional[str] = None) -> None:
    """Drop a single card from the cache, or the whole cache if no key
    given. Useful after a peer rotates keys or upgrades their card."""
    if card_url is None:
        _card_cache.clear()
        return
    _card_cache.pop(card_url, None)


# ── Policy ────────────────────────────────────────────────────────────


def infer_intent(peer_entity_id: str) -> Intent:
    """Cheap heuristic: ``zns:svc:…`` → service, anything else → agent.
    Callers that know better can pass ``intent=`` explicitly to
    :func:`dispatch`."""
    if ":svc:" in peer_entity_id:
        return Intent.SERVICE_CALL
    return Intent.AGENT_TO_AGENT


def pick_transport(
    peer_card: Optional[dict[str, Any]],
    *,
    intent: Intent,
    hints: Optional[TransportHints] = None,
) -> Transport:
    """Apply the four-line policy. Falls through to SEND when the peer's
    card is unavailable — sync is the safest universally-supported
    fallback."""
    x_zynd = (peer_card or {}).get("x-zynd") or {}
    if x_zynd.get("requiresPushNotification") is True:
        return Transport.PUSH

    if hints and hints.force is not None:
        return hints.force

    caps = (peer_card or {}).get("capabilities") or {}
    if intent == Intent.AGENT_TO_AGENT:
        if caps.get("pushNotifications") is True:
            return Transport.PUSH
        return Transport.SEND

    # SERVICE_CALL
    return Transport.SEND


# ── Callback registrar protocol ──────────────────────────────────────


class CallbackRegistrar(Protocol):
    """Plugged in by ``services.callbacks`` (Phase 3). The dispatcher
    needs ``register`` (creates the row, returns the credentials the
    peer should use to push back), ``mark_peer_task`` (link Task.id
    once known), and ``record_inline_result`` (synthesize a callback
    result when the peer completed inline rather than pushing — A2A
    permits both, so the surface should be uniform)."""

    async def register(
        self,
        *,
        user_id: str,
        thread_id: str,
        peer_agent_id: str,
        our_message_id: str,
        origin_kind: str,
        origin_ref: dict[str, Any],
        peer_a2a_url: Optional[str] = None,
    ) -> tuple[str, str, str]:
        """Returns ``(callback_id, push_url, push_token)``."""
        ...

    async def mark_peer_task(self, callback_id: str, peer_task_id: str) -> None:
        ...

    async def record_inline_result(
        self,
        callback_id: str,
        *,
        task: dict[str, Any],
        reply_text: Optional[str],
    ) -> None:
        """Treat an inline-completed task as if the peer had pushed it
        back. Writes a callback_results row so the frontend's realtime
        subscription picks it up."""
        ...


# Allow `dispatch()` to be called without a registrar — useful for unit
# tests and for the brief Phase 2 → Phase 3 interlude where the table
# doesn't exist yet. When PUSH is selected and no registrar is wired,
# the dispatcher transparently degrades to SEND and logs a warning.
_callback_registrar: Optional[CallbackRegistrar] = None


def configure_callback_registrar(reg: Optional[CallbackRegistrar]) -> None:
    """Wire (or unwire) the persistent callback registrar. Phase 3
    calls this at module import."""
    global _callback_registrar
    _callback_registrar = reg


# ── Main entry point ─────────────────────────────────────────────────


CardFetcher = Callable[[str], Awaitable[Optional[dict[str, Any]]]]


async def dispatch(
    client: A2AClient,
    *,
    peer_entity_id: str,
    peer_a2a_url: str,
    peer_card_url: str,
    user_id: str,
    thread_id: str,
    context_id: str,
    text: str = "",
    data: Any = None,
    task_id: Optional[str] = None,
    intent: Optional[Intent] = None,
    hints: Optional[TransportHints] = None,
    origin_kind: str = "unknown",
    origin_ref: Optional[dict[str, Any]] = None,
) -> DispatchResult:
    """Send a message to a peer using the transport their card permits.

    The caller supplies routing identity (``user_id`` + ``thread_id``)
    so push-mode callbacks can be correlated back. ``origin_kind`` /
    ``origin_ref`` describe what triggered the send (e.g.
    ``"chat"`` + ``{"chat_message_id": ...}``) so the eventual reply
    can be routed to the right surface in the UI.
    """
    if intent is None:
        intent = infer_intent(peer_entity_id)

    peer_card = await _fetch_peer_card_cached(client, peer_card_url)
    transport = pick_transport(peer_card, intent=intent, hints=hints)

    if transport == Transport.STREAM:
        # Stream is caller-driven: we hand back the async iterator and
        # let them consume it (and write events into chat_messages or
        # a SSE proxy at their convenience).
        stream = client.stream(
            peer_a2a_url,
            context_id=context_id,
            text=text,
            data=data,
            task_id=task_id,
        )
        return DispatchResult(transport=Transport.STREAM, stream=stream)

    if transport == Transport.GET:
        # GET is only sensible when we already have a task_id.
        if not task_id:
            raise ValueError("Transport.GET requires task_id")
        task = await client.get_task(peer_a2a_url, task_id)
        return DispatchResult(transport=Transport.GET, task=task)

    if transport == Transport.PUSH:
        if _callback_registrar is None:
            logger.warning(
                "transport.dispatch: PUSH chosen but no callback registrar wired — "
                "downgrading to SEND. Wire services.callbacks.registrar."
            )
            transport = Transport.SEND
        else:
            # Generate a fresh messageId so the registrar can store it
            # before we send. We'll pass the same id into client.send
            # via the rebuilt message — but A2AClient owns messageId
            # generation. Workaround: register first with a placeholder
            # id, then update once the receiver responds with their
            # Task.id.
            our_message_id = f"out-{int(time.time() * 1000)}"
            callback_id, push_url, push_token = await _callback_registrar.register(
                user_id=user_id,
                thread_id=thread_id,
                peer_agent_id=peer_entity_id,
                our_message_id=our_message_id,
                origin_kind=origin_kind,
                origin_ref=origin_ref or {},
                peer_a2a_url=peer_a2a_url,
            )
            task = await client.send(
                peer_a2a_url,
                context_id=context_id,
                text=text,
                data=data,
                task_id=task_id,
                push_url=push_url,
                push_token=push_token,
            )
            # Best-effort: link the callback row to the peer's task id
            # so phase 4's correlation has another join key beyond the
            # bearer token.
            peer_task_id = task.get("id") if isinstance(task, dict) else None
            if peer_task_id:
                try:
                    await _callback_registrar.mark_peer_task(callback_id, peer_task_id)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "transport.dispatch: mark_peer_task failed cb=%s peer_task=%s: %s",
                        callback_id, peer_task_id, e,
                    )

            # If the peer answered inline (terminal state with a real reply
            # in the immediate response), no push will ever come — synthesize
            # the result now so the frontend sees it via realtime.
            # Skip when the response is a deferred push ack: the agent sets
            # state=completed but shortlist=null and delivery="push", meaning
            # the real result is still coming via push/poll. Recording it now
            # would mark the callback "received" with null answer and the
            # poller would never run.
            inline_state = ((task.get("status") or {}).get("state")) if isinstance(task, dict) else None
            if inline_state in ("completed", "failed", "rejected", "canceled"):
                is_deferred = _is_deferred_push_ack(task)
                if is_deferred:
                    logger.info(
                        "transport.dispatch: cb=%s state=%s but deferred push ack — skipping inline record, waiting for push/poll",
                        callback_id, inline_state,
                    )
                else:
                    reply_text = _extract_reply_text_from_task(task)
                    try:
                        await _callback_registrar.record_inline_result(
                            callback_id,
                            task=task,
                            reply_text=reply_text,
                        )
                    except Exception as e:  # noqa: BLE001
                        logger.warning(
                            "transport.dispatch: record_inline_result failed cb=%s: %s",
                            callback_id, e,
                        )

            return DispatchResult(
                transport=Transport.PUSH,
                task=task,
                callback_id=callback_id,
                push_url=push_url,
                push_token=push_token,
            )

    # SEND (default & fallback)
    task = await client.send(
        peer_a2a_url,
        context_id=context_id,
        text=text,
        data=data,
        task_id=task_id,
    )
    return DispatchResult(transport=Transport.SEND, task=task)
