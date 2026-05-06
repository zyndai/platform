"""
A2A v0.3 protocol primitives for agent-persona.

Vendored from the zyndai_agent.a2a SDK (v0.6.0) so we don't pull in
the SDK's flask + langchain + eth-account dependencies just to use
the wire format. Identity functions are sourced from our local
agent.zynd_identity module instead of the SDK's ed25519_identity.

Public API:
  canonical_bytes — RFC 8785 JCS for cross-language signing
  Message, Task, TaskStatus, Artifact, Part, TextPart, DataPart, FilePart
  ZyndAuth, DerivationProof
  TERMINAL_STATES, INTERRUPTED_STATES
  RPC_* and A2A_* and ZYND_* error codes
  sign_message, verify_message, ZyndAuthError, ReplayCache, AuthMode
  ZYND_AUTH_KEY, ZYND_AUTH_VERSION, ZYND_AUTH_DOMAIN_TAG
"""

from agent.a2a.canonical import canonical_json, canonical_bytes
from agent.a2a.types import (
    # Wire types
    Message,
    Part,
    TextPart,
    FilePart,
    DataPart,
    FileWithBytes,
    FileWithUri,
    Task,
    Artifact,
    TaskStatus,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    PushNotificationConfig,
    TaskPushNotificationConfig,
    ZyndAuth,
    DerivationProof,
    JsonRpcRequest,
    MessageSendParams,
    TaskIdParams,
    TaskQueryParams,
    # Constants
    TERMINAL_STATES,
    INTERRUPTED_STATES,
    ZYND_AUTH_KEY,
    ZYND_AUTH_VERSION,
    ZYND_AUTH_DOMAIN_TAG,
    # Error codes
    RPC_PARSE_ERROR,
    RPC_INVALID_REQUEST,
    RPC_METHOD_NOT_FOUND,
    RPC_INVALID_PARAMS,
    RPC_INTERNAL_ERROR,
    A2A_TASK_NOT_FOUND,
    A2A_TASK_NOT_CANCELABLE,
    A2A_PUSH_NOTIFICATION_NOT_SUPPORTED,
    A2A_UNSUPPORTED_OPERATION,
    A2A_CONTENT_TYPE_NOT_SUPPORTED,
    A2A_INVALID_AGENT_RESPONSE,
    ZYND_AUTH_FAILED,
    ZYND_REPLAY_DETECTED,
    ZYND_AUTH_EXPIRED,
)
from agent.a2a.auth import (
    sign_message,
    verify_message,
    ZyndAuthError,
    ReplayCache,
    AuthMode,
)
from agent.a2a.client import (
    A2AClient,
    A2AError,
    derive_a2a_url_from_legacy_webhook,
    extract_reply_text,
    resolve_a2a_url,
)
