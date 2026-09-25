"""
User-facing error sanitization for MCP tools.

Tools should log raw exceptions for debugging but return short, actionable
error payloads to the LLM so the user sees plain-language explanations
instead of raw API bodies or stack traces.

Every user-facing error follows the same shape:
  - `error`        — one-line *what* went wrong.
  - `error_message` — human *why* it happened (non-technical).
  - `hint`         — concrete next step the user can take.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _classify(raw: str, operation: str) -> tuple[str, str, str]:
    """
    Map a raw exception/message string to three non-technical sentences.

    Returns ``(what, why, hint)``. No stack traces, HTTP URLs, or internal
    identifiers are returned.
    """
    lowered = (raw or "").lower()

    # The "operation" string is meant to read as a verb phrase after
    # "Couldn't", e.g. "post to X", "read your calendar". If it's empty
    # or clearly not a verb phrase, fall back to a generic title.
    if operation and not operation.lower().startswith(("this ", "the ", "a ", "an ")):
        title = f"Couldn't {operation}"
    else:
        title = "Something went wrong"

    provider = (operation or "this service").split()[0]

    if "not connected" in lowered or "no active persona" in lowered:
        return (
            f"{provider} isn't connected yet",
            "I can't reach it because it hasn't been linked to your account.",
            f"Connect {provider} in Settings → Accounts and try again.",
        )

    if any(tok in lowered for tok in ("token", "credentials", "unauthorized", "revoked", "expired")) or "401" in lowered:
        return (
            f"Your {provider} connection expired",
            "The stored login for this account is no longer valid.",
            f"Reconnect {provider} in Settings → Accounts and try again.",
        )

    if "rate limit" in lowered or "too many requests" in lowered or "429" in lowered:
        return (
            f"{provider} is busy right now",
            "It's receiving too many requests at the moment.",
            "Wait a minute and try again.",
        )

    if "timeout" in lowered or "timed out" in lowered:
        return (
            f"{provider} didn't respond in time",
            "The request took longer than expected and timed out.",
            "Try again in a moment.",
        )

    if (
        "invalid input syntax" in lowered
        or "22p02" in lowered
        or ("invalid" in lowered and "uuid" in lowered)
    ):
        return (
            f"That {provider} ID looks wrong",
            "The ID passed in doesn't match the format the database expects — it's likely truncated or malformed, not a real record.",
            "Look up the correct ID again rather than reusing a shortened or guessed one.",
        )

    if "not found" in lowered or "404" in lowered or "doesn't exist" in lowered or "does not exist" in lowered:
        return (
            f"That {provider} item wasn't found",
            "It may have been removed, or the name might be wrong.",
            "Double-check the name or ID and try again.",
        )

    if any(tok in lowered for tok in ("permission", "forbidden", "access denied")) or "403" in lowered:
        return (
            f"{provider} refused the request",
            "Your account doesn't have permission for this action.",
            "Check the permissions for this account, or try a different action.",
        )

    if "duplicate" in lowered or "already exists" in lowered:
        return (
            f"That {provider} item already exists",
            "The request would create a duplicate.",
            "Try a different name or check what's already there.",
        )

    if any(tok in lowered for tok in ("network", "unreachable", "connection", "dns", "refused")):
        return (
            f"I couldn't reach {provider}",
            "A network problem prevented the connection.",
            "Check your internet connection and try again.",
        )

    return (
        title,
        "A temporary technical problem occurred while handling the request.",
        "Please try again in a moment.",
    )


def friendly_error(operation: str, exception: Exception | None = None, *, hint: str = "") -> dict:
    """
    Return a user-facing error dict and log the raw exception server-side.

    Args:
        operation: Human-readable name of what the tool was trying to do,
            e.g. "post to X" or "read your calendar".
        exception: The raw exception. Logged but never returned verbatim.
        hint: Optional next-step hint. If omitted, a sensible default is chosen.

    Returns:
        {"success": False, "error": "<what>", "error_message": "<why>", "hint": "<next step>"}
    """
    raw = str(exception) if exception is not None else ""
    logger.warning("[%s] %s", operation, raw)

    what, why, default_hint = _classify(raw, operation)
    return {
        "success": False,
        "error": what,
        "error_message": why,
        "hint": hint or default_hint,
    }


def friendly_error_message(operation: str, message: str, *, hint: str = "") -> dict:
    """
    Same as ``friendly_error`` but for cases where we already have an error
    string instead of an exception object.
    """
    logger.warning("[%s] %s", operation, message)

    what, why, default_hint = _classify(message, operation)
    return {
        "success": False,
        "error": what,
        "error_message": why,
        "hint": hint or default_hint,
    }
