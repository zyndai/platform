"""
Minimal async A2A v0.3 JSON-RPC client.

Used by mcp/tools/zynd_network.message_zynd_agent (and any future
outbound flows) to talk to other personas. Signs every outbound
Message with the caller's keypair, posts as JSON-RPC 2.0 to the
target's `/a2a/v1` endpoint, and returns the resulting Task.

Compared to the SDK's a2a.client.A2AClient: same wire format, but
async (httpx.AsyncClient), no SSE for now (phase 3.3 wires that up
in this same module), and no card-cache. We use httpx because it's
already a transitive dependency via supabase, and async because the
caller (handle_user_message) runs on the FastAPI event loop.
"""

import json
import logging
import uuid
from typing import Any, AsyncIterator, Optional

import httpx

from agent.a2a.auth import sign_message
from agent.zynd_identity import Keypair

logger = logging.getLogger(__name__)


class A2AError(Exception):
    """Raised when an A2A JSON-RPC call returns an error envelope.

    The receiver's reason — `data.reason` if present, otherwise the
    bare `message` — is preserved so the caller can decide whether
    to retry, escalate to the user, or surface a structured failure.
    """

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(f"A2A error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data

    @property
    def reason(self) -> Optional[str]:
        if isinstance(self.data, dict):
            return self.data.get("reason")
        return None


class A2AClient:
    """Async JSON-RPC client for cross-agent message/send.

    Holds the caller's keypair + entity_id so each call doesn't have to
    pass them. Card discovery is the caller's job — we accept a fully
    resolved A2A endpoint URL.
    """

    def __init__(
        self,
        keypair: Keypair,
        entity_id: str,
        *,
        fqan: Optional[str] = None,
        developer_proof: Optional[dict] = None,
        timeout: float = 90.0,
    ):
        self._keypair = keypair
        self._entity_id = entity_id
        self._fqan = fqan
        self._developer_proof = developer_proof
        self._timeout = timeout

    async def send(
        self,
        a2a_url: str,
        *,
        context_id: str,
        text: str = "",
        data: Any = None,
        task_id: Optional[str] = None,
        push_url: Optional[str] = None,
        push_token: Optional[str] = None,
    ) -> dict[str, Any]:
        """Sync (blocking) message/send. Returns the receiver's Task dict.

        text and/or data may be supplied. If both are present, the
        DataPart precedes the TextPart in the parts array (matches the
        adapter's part-ordering convention from the SDK).

        Raises:
            A2AError on a JSON-RPC error envelope from the receiver.
            httpx.HTTPError on transport-level failure.
        """
        msg = self._build_signed_message(
            text=text,
            data=data,
            context_id=context_id,
            task_id=task_id,
        )

        params: dict[str, Any] = {"message": msg}
        if push_url:
            push_cfg: dict[str, Any] = {"url": push_url}
            if push_token:
                push_cfg["token"] = push_token
            params["configuration"] = {"pushNotificationConfig": push_cfg}

        body = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "message/send",
            "params": params,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as h:
            resp = await h.post(a2a_url, json=body)
            resp.raise_for_status()
            envelope = resp.json()

        return self._unwrap(envelope)

    async def stream(
        self,
        a2a_url: str,
        *,
        context_id: str,
        text: str = "",
        data: Any = None,
        task_id: Optional[str] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Async iterator over status-update / artifact-update events
        emitted by the server's message/stream SSE response.

        Yields each event's `result` field (a dict with `kind` ∈
        {"status-update", "artifact-update"}). Raises A2AError on the
        first error envelope; the stream ends on the event with
        `final == True` or when the server closes the connection.
        """
        msg = self._build_signed_message(
            text=text, data=data, context_id=context_id, task_id=task_id,
        )
        body = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "message/stream",
            "params": {"message": msg},
        }
        async for ev in self._stream_call(a2a_url, body):
            yield ev

    async def resubscribe(
        self,
        a2a_url: str,
        task_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Re-attach an SSE stream to a task already in flight (e.g.
        after a transport reconnect). Yields the same kinds of events
        as `stream`."""
        body = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tasks/resubscribe",
            "params": {"id": task_id},
        }
        async for ev in self._stream_call(a2a_url, body):
            yield ev

    async def _stream_call(
        self,
        a2a_url: str,
        body: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self._timeout) as h:
            async with h.stream("POST", a2a_url, json=body) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if not line.startswith("data: "):
                        # Spec allows comments / heartbeats — ignore.
                        continue
                    raw = line[len("data: "):]
                    try:
                        envelope = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning(f"A2AClient.stream: malformed SSE line {raw!r}")
                        continue
                    if "error" in envelope:
                        err = envelope["error"]
                        raise A2AError(
                            code=int(err.get("code", -32603)),
                            message=str(err.get("message", "unknown error")),
                            data=err.get("data"),
                        )
                    result = envelope.get("result")
                    if result is not None:
                        yield result

    async def get_task(
        self,
        a2a_url: str,
        task_id: str,
        *,
        history_length: Optional[int] = None,
    ) -> dict[str, Any]:
        """Read-only Task lookup by id. Returns the Task dict.

        history_length: clamp Task.history to the last N messages.
        Useful when polling — avoids re-pulling the entire history
        every time. None means "include the full history the server
        has on hand" (the server itself may apply a retention limit).
        """
        params: dict[str, Any] = {"id": task_id}
        if history_length is not None:
            params["historyLength"] = history_length
        return await self._call(a2a_url, "tasks/get", params)

    async def cancel_task(self, a2a_url: str, task_id: str) -> dict[str, Any]:
        """Force a non-terminal Task into 'canceled' state. Returns the
        updated Task dict. Raises A2AError(A2A_TASK_NOT_CANCELABLE) when
        the task is already in a terminal state.
        """
        return await self._call(a2a_url, "tasks/cancel", {"id": task_id})

    async def _call(self, a2a_url: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Generic JSON-RPC call helper for read-only / non-Message methods.
        Public methods (`send`, `get_task`, `cancel_task`) wrap this with
        their own param shapes."""
        body = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as h:
            resp = await h.post(a2a_url, json=body)
            resp.raise_for_status()
            envelope = resp.json()
        return self._unwrap(envelope)

    async def set_push_notification_config(
        self,
        a2a_url: str,
        task_id: str,
        push_url: str,
        push_token: Optional[str] = None,
    ) -> dict[str, Any]:
        """Register or update a pushNotificationConfig on an existing task."""
        cfg: dict[str, Any] = {"url": push_url}
        if push_token:
            cfg["token"] = push_token
        return await self._call(
            a2a_url,
            "tasks/pushNotificationConfig/set",
            {"taskId": task_id, "pushNotificationConfig": cfg},
        )

    async def get_push_notification_config(
        self,
        a2a_url: str,
        task_id: str,
    ) -> dict[str, Any]:
        """Read back the current pushNotificationConfig for a task."""
        return await self._call(
            a2a_url,
            "tasks/pushNotificationConfig/get",
            {"id": task_id},
        )

    async def fetch_card(self, card_url: str) -> dict[str, Any]:
        """GET a peer's `.well-known/agent-card.json`.

        Phase 3 doesn't verify the card's detached-JWS signature — the
        receiver's per-message x-zynd-auth is the actual identity check.
        Card verification is a phase-4 hardening pass.
        """
        async with httpx.AsyncClient(timeout=15) as h:
            resp = await h.get(card_url)
            resp.raise_for_status()
            return resp.json()

    # ── internals ───────────────────────────────────────────────────

    def _build_signed_message(
        self,
        *,
        text: str,
        data: Any,
        context_id: str,
        task_id: Optional[str],
    ) -> dict[str, Any]:
        parts: list[dict[str, Any]] = []
        if data is not None:
            parts.append({"kind": "data", "data": data})
        if text:
            parts.append({"kind": "text", "text": text})
        if not parts:
            # An empty message would still be valid, but signing a no-op
            # is almost certainly a bug — fail loud rather than send it.
            raise ValueError("A2AClient.send: at least one of text/data must be provided")

        msg: dict[str, Any] = {
            "kind": "message",
            "messageId": str(uuid.uuid4()),
            "role": "user",
            "parts": parts,
            "contextId": context_id,
        }
        if task_id:
            msg["taskId"] = task_id

        sign_message(
            msg,
            self._keypair,
            self._entity_id,
            fqan=self._fqan,
            developer_proof=self._developer_proof,
        )
        return msg

    @staticmethod
    def _unwrap(envelope: dict[str, Any]) -> dict[str, Any]:
        if "error" in envelope:
            err = envelope["error"]
            raise A2AError(
                code=int(err.get("code", -32603)),
                message=str(err.get("message", "unknown JSON-RPC error")),
                data=err.get("data"),
            )
        result = envelope.get("result")
        if not isinstance(result, dict):
            raise A2AError(-32603, "Receiver returned a non-object result.", data={"envelope": envelope})
        return result


# ── Convenience helpers ─────────────────────────────────────────────


def derive_a2a_url_from_legacy_webhook(webhook_url: str) -> Optional[str]:
    """Convert the legacy v2 webhook URL stored on persona_agents into
    the v3 JSON-RPC endpoint URL.

    Input shape: `<base>/api/persona/webhooks/<user_id>` (or `.../sync`)
    Output:      `<base>/api/persona/<user_id>/a2a/v1`

    Returns None if the input doesn't match the legacy pattern.
    """
    if not webhook_url:
        return None
    base = webhook_url.rstrip("/")
    if base.endswith("/sync"):
        base = base[: -len("/sync")]
    marker = "/api/persona/webhooks/"
    idx = base.rfind(marker)
    if idx < 0:
        return None
    host = base[:idx]
    user_id = base[idx + len(marker):]
    if not user_id or "/" in user_id:
        return None
    return f"{host}/api/persona/{user_id}/a2a/v1"


def resolve_a2a_url(stored_url: str) -> Optional[str]:
    """Return a v3 JSON-RPC endpoint URL given either a v3 URL or a
    legacy v2 webhook URL.

    Why both: persona_agents.webhook_url stores whichever URL the
    persona was registered with at the time. Personas registered before
    phase 4.1 hold a legacy URL; personas after hold a v3 URL. The
    callers (message_zynd_agent, agent-send, etc.) shouldn't have to
    care — this resolver hides the detail.
    """
    if not stored_url:
        return None
    cleaned = stored_url.rstrip("/")
    if cleaned.endswith("/a2a/v1"):
        return cleaned
    return derive_a2a_url_from_legacy_webhook(stored_url)


def extract_reply_text(task: dict[str, Any]) -> str:
    """Pull the agent's reply text out of a Task returned from message/send.

    Looks at status.message.parts (the canonical place for the agent's
    final say) first, then falls back to the first artifact's TextParts.
    Returns the empty string when neither is populated — the caller can
    decide what to do with that.
    """
    status = task.get("status") or {}
    sm = status.get("message") or {}
    chunks = _join_text_parts(sm.get("parts"))
    if chunks:
        return chunks
    for art in task.get("artifacts") or []:
        chunks = _join_text_parts(art.get("parts"))
        if chunks:
            return chunks
    return ""


def _join_text_parts(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    out = []
    for p in parts:
        if isinstance(p, dict) and p.get("kind") == "text":
            t = p.get("text") or ""
            if t:
                out.append(t)
    return "\n".join(out)
