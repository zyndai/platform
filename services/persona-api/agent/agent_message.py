"""
AgentMessage — the structured message format agents exchange over
webhooks. Drop-in replacement for `zyndai_agent.message.AgentMessage`.

We preserve the exact wire format the SDK was using (same keys in
`to_dict` / `from_dict`) so cross-agent traffic stays compatible with
any other client still running the SDK. Specifically:

  - `to_dict` includes BOTH `content` and `prompt` keys (same value).
    Some receivers look up one, some look up the other.
  - `from_dict` accepts either key for the text body.
  - `conversation_id` and `message_id` auto-generate UUIDs if missing.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AgentMessage:
    content: str
    sender_id: str = "unknown"
    receiver_id: Optional[str] = None
    message_type: str = "query"
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sender_did: Any = None
    sender_public_key: Optional[str] = None
    in_reply_to: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire format consumers expect."""
        return {
            "content": self.content,
            "prompt": self.content,  # legacy alias — some receivers read this
            "sender_id": self.sender_id,
            "sender_did": self.sender_did,
            "sender_public_key": self.sender_public_key,
            "receiver_id": self.receiver_id,
            "message_type": self.message_type,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "in_reply_to": self.in_reply_to,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentMessage":
        content = data.get("prompt", data.get("content", "")) or ""
        return cls(
            content=content,
            sender_id=data.get("sender_id") or "unknown",
            receiver_id=data.get("receiver_id"),
            message_type=data.get("message_type") or "query",
            message_id=data.get("message_id") or str(uuid.uuid4()),
            conversation_id=data.get("conversation_id") or str(uuid.uuid4()),
            sender_did=data.get("sender_did"),
            sender_public_key=data.get("sender_public_key"),
            in_reply_to=data.get("in_reply_to"),
            metadata=data.get("metadata") or {},
            timestamp=float(data.get("timestamp") or time.time()),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "AgentMessage":
        try:
            return cls.from_dict(json.loads(json_str))
        except Exception:
            return cls(content=json_str, sender_id="unknown", message_type="raw")
