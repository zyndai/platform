
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid

import config
from mcp.server import mcp_server
from services.token_store import list_connected_providers, is_linkedin_scraped
from agent.memory_context import load_memory_context, format_context_for_prompt, ingest_conversation

# ── Conversation memory ──────────────────────────────────────────────
_conversations: dict[str, list[dict]] = {}

def _persist_chat_message(
    user_id: str,
    conversation_id: str,
    role: str,
    content: str,
    actions: list[dict] | None = None,
) -> None:
    """Best-effort write to `chat_messages`. Failures don't break the
    LLM turn — we log and move on. Skipped for agent-to-agent
    conversations (which use a `thread:<uuid>` conversation_id and
    have their own DM-side persistence in dm_messages)."""
    if not conversation_id or conversation_id.startswith("thread:"):
        return
    if not content:
        return
    try:
        sb = config.get_supabase()
        row = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
        }
        if actions:
            row["actions"] = actions
        sb.table("chat_messages").insert(row).execute()
    except Exception as e:  # noqa: BLE001
        print(f"[orchestrator] persist chat_messages failed: {type(e).__name__}: {e}")

# =====================================================================
# External-mode permission gating
# =====================================================================
#
# When a foreign agent reaches us via the persona webhook, the orchestrator
# runs in "external" mode. We use a strict ALLOWLIST for tools — by default
# only network discovery is available, and per-thread permission flags
# (configured by the principal in the connection settings drawer) open up
# additional tool sets.
#
# This is defense in depth: the system prompt also tells the LLM what's
# off-limits, but we additionally hard-block tool calls in the orchestrator
# loop so a hallucinated call cannot leak data or perform actions the
# principal hasn't granted.

# Tools that are ALWAYS available in external mode (default-allow set).
# These are read-only network operations that any connected peer can do —
# they reveal nothing private about the principal beyond what's already
# on the public registry card.
EXTERNAL_DEFAULT_ALLOWED: set[str] = {
    "search_zynd_network",
    "search_zynd_personas",
    "get_persona_profile",
    "list_my_connections",
    "check_connection_status",
    "get_current_time",
    # Zynd Network service DISCOVERY: read-only/stateless from our side.
    # Safe to expose in external + group contexts so the agent can see what
    # capabilities exist. The INVOCATION tools (call_zynd_service,
    # call_zynd_agent) are deliberately NOT here: both sign as the principal,
    # so exposing them externally would let a foreign agent make our persona
    # fire signed calls under our identity (confused-deputy). Invocation is
    # internal-only.
    "search_zynd_services",
    "get_zynd_service_card",
}

# Permission flag → set of additional tools the flag unlocks in external mode.
# Anything not listed in DEFAULT_ALLOWED or here is forbidden externally.
EXTERNAL_PERMISSION_GATES: dict[str, set[str]] = {
    "can_query_availability": {
        "list_calendar_events",
    },
    "can_post_on_my_behalf": {
        # Calendar mutations
        "create_calendar_event",
        "delete_calendar_event",
        # Social posting
        "post_tweet",
        "send_twitter_dm",
        "post_to_linkedin",
        "send_linkedin_dm",
        # Email
        "send_gmail_email",
        # Document/sheet/drive write actions
        "create_google_doc",
        "append_to_google_doc",
        "create_google_sheet",
        "append_to_google_sheet",
        "create_google_drive_folder",
        "move_google_drive_file",
        # Notion writes
        "create_notion_page",
        "update_notion_page",
        "create_notion_database",
        "append_notion_blocks",
    },
    # A foreign agent with this permission can PROPOSE meetings to the principal.
    # (respond_to_meeting is intentionally NOT here — the recipient responds from
    # their own UI or their own internal-mode chat, not via cross-agent calls.
    # list_pending_meetings is also internal-only — it exposes the user's plate.)
    "can_request_meetings": {
        "propose_meeting",
        "propose_group_meeting",
    },
    # `can_view_full_profile` doesn't gate tools; it only gates the persona
    # briefing rendered into the system prompt (handled in _format_user_brief).
}

# ── Approval gate ────────────────────────────────────────────────────
# Tool calls in this set are commitment-class — they bind the user to
# something other agents (or other users) will see. In external mode we
# never let them fire silently. We persist a row to pending_approvals
# instead, and the LLM's reply for that turn becomes a "I've staged this
# with my principal" line. The user resolves the approval from the home
# chat or the thread page; on yes the tool re-fires with the saved args.
APPROVAL_REQUIRED_TOOLS: set[str] = {
    "propose_meeting",
    "propose_group_meeting",
    # Calendar mutations — a foreign agent (or a teammate's persona in a
    # group) must never silently write to or delete from the principal's
    # calendar. The principal sees a pending_approvals row and decides.
    "create_calendar_event",
    "delete_calendar_event",
    # Outbound social / email — same rationale.
    "send_gmail_email",
    "post_tweet",
    "send_twitter_dm",
    "post_to_linkedin",
    "send_linkedin_dm",
}

def _summarize_for_approval(fn_name: str, fn_args: dict, sender_agent_id: str | None) -> str:
    partner = sender_agent_id or "the other agent"
    if fn_name == "propose_meeting":
        title = fn_args.get("title") or "Untitled meeting"
        start = fn_args.get("start_time") or "?"
        end   = fn_args.get("end_time")   or ""
        when = f"{start}" + (f" → {end}" if end else "")
        return f"Propose “{title}” ({when}) with {partner}"
    if fn_name == "propose_group_meeting":
        title = fn_args.get("title") or "Untitled meeting"
        start = fn_args.get("start_time") or "?"
        end   = fn_args.get("end_time")   or ""
        when = f"{start}" + (f" → {end}" if end else "")
        return f"Schedule “{title}” ({when}) in your group — requested by {partner}. Approving will create the event on your calendar and invite every other member."
    if fn_name == "create_calendar_event":
        title = fn_args.get("summary") or fn_args.get("title") or "Untitled event"
        start = fn_args.get("start_time") or fn_args.get("start") or "?"
        end   = fn_args.get("end_time")   or fn_args.get("end")   or ""
        when = f"{start}" + (f" → {end}" if end else "")
        return f"Add “{title}” to your calendar ({when}) — requested by {partner}"
    if fn_name == "delete_calendar_event":
        eid = fn_args.get("event_id") or "?"
        return f"Delete calendar event {eid} — requested by {partner}"
    if fn_name == "send_gmail_email":
        to = fn_args.get("to") or "?"
        subj = fn_args.get("subject") or "(no subject)"
        return f"Send email to {to}: “{subj}” — requested by {partner}"
    if fn_name in ("post_tweet", "post_to_linkedin"):
        text = (fn_args.get("text") or fn_args.get("content") or "").strip()
        preview = (text[:80] + "…") if len(text) > 80 else text
        platform = "Twitter" if fn_name == "post_tweet" else "LinkedIn"
        return f"Post to {platform}: “{preview}” — requested by {partner}"
    if fn_name in ("send_twitter_dm", "send_linkedin_dm"):
        to = fn_args.get("recipient") or fn_args.get("to") or "?"
        platform = "Twitter" if fn_name == "send_twitter_dm" else "LinkedIn"
        return f"Send {platform} DM to {to} — requested by {partner}"
    return f"Run {fn_name} (requested by {partner})"

def _thread_id_from_conv(conversation_id: str | None) -> str | None:
    """conversation_id is `thread:<uuid>` for agent-to-agent webhook turns
    (set by api/persona.py:process_async_webhook). For internal user chat
    it's a different shape, so we only return the uuid when the prefix
    matches."""
    if not conversation_id:
        return None
    if conversation_id.startswith("thread:"):
        return conversation_id.split(":", 1)[1]
    return None

def _group_id_from_conv(conversation_id: str | None) -> str | None:
    """conversation_id is `group:<group_id>:<target_uid>` for group-dispatch
    turns (set by agent/group_dispatch.py:_conversation_id_for). Returns the
    group_id slice; None for any other shape."""
    if not conversation_id or not conversation_id.startswith("group:"):
        return None
    parts = conversation_id.split(":", 2)
    return parts[1] if len(parts) >= 2 else None

def _is_seeded_user(user_id: str) -> bool:
    """Seeded test personas (created by scripts/seed_personas.py) have
    `user_metadata.seeded = true` on their auth row. Real human users
    don't. We bypass the approval gate for seeded users so end-to-end
    testing doesn't dead-end on an approval card no human can resolve."""
    try:
        import requests as _req
        url = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{user_id}"
        headers = {
            "apikey": config.SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        }
        r = _req.get(url, headers=headers, timeout=5)
        if not r.ok:
            return False
        meta = (r.json() or {}).get("user_metadata") or {}
        return bool(meta.get("seeded"))
    except Exception:
        return False

def _ping_telegram_approval(user_id: str, summary: str) -> None:
    """Fire-and-forget Telegram ping for a freshly-staged approval.

    Called from `_maybe_stage_approval` after the DB insert succeeds.
    The actual send goes through `services.telegram_notify.notify_user`,
    which is a no-op if the user hasn't linked Telegram — so we don't
    have to check for that here.

    We schedule via `asyncio.create_task` if we're inside an event loop
    (the normal webhook path), and fall back to `asyncio.run` in a
    detached thread otherwise so sync callers don't crash.
    """
    msg = (
        f"🔔 *Approval needed*\n{summary}\n\n"
        "Open the dashboard to accept or decline: "
        "https://persona.zynd.ai/dashboard/approvals"
    )
    try:
        from services.telegram_notify import notify_user
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.create_task(notify_user(user_id, msg))
        else:
            import threading

            def _runner():
                try:
                    asyncio.run(notify_user(user_id, msg))
                except Exception as e:
                    print(f"[orchestrator] approval ping runner failed: {e}")

            threading.Thread(target=_runner, daemon=True).start()
    except Exception as e:
        # Notifications must never break the orchestrator path.
        print(f"[orchestrator] approval ping failed: {e}")

def _maybe_stage_approval(
    user_id: str,
    fn_name: str,
    fn_args: dict,
    is_external: bool,
    conversation_id: str | None,
    sender_agent_id: str | None,
) -> dict | None:
    """If this tool call needs gating, persist a pending_approvals row
    and return a structured 'queued' result for the LLM to summarize back
    to the foreign agent. Returns None when no gating is needed (caller
    proceeds with normal tool execution)."""
    if not is_external:
        return None
    if fn_name not in APPROVAL_REQUIRED_TOOLS:
        return None
    # Bypass for seeded test personas — no human is watching their chat.
    if _is_seeded_user(user_id):
        print(f"[orchestrator] approval gate bypassed for seeded user {user_id[:8]}")
        return None
    try:
        sb = config.get_supabase()
        thread_id = _thread_id_from_conv(conversation_id)
        summary = _summarize_for_approval(fn_name, fn_args, sender_agent_id)
        row = sb.table("pending_approvals").insert({
            "user_id":   user_id,
            "thread_id": thread_id,
            "tool_name": fn_name,
            "tool_args": fn_args,
            "summary":   summary,
            "status":    "pending",
        }).execute()
        approval_id = row.data[0]["id"] if row.data else None
        print(f"[orchestrator] staged approval {approval_id} for {fn_name}: {summary}")

        # Push a Telegram ping to the principal so they actually see the
        # approval card without having the dashboard open. Best-effort —
        # fired as a background task so it never blocks the webhook /
        # orchestrator turn that staged the row.
        _ping_telegram_approval(user_id, summary)

        return {
            "status": "queued_for_approval",
            "approval_id": approval_id,
            "summary": summary,
            "instruction": (
                "Do NOT call this tool again on this turn. The action is queued "
                "for human approval. In your reply, tell the foreign agent the "
                "request has been staged with your principal and they'll get "
                "back when it's confirmed. Then stop — escalate to your human."
            ),
        }
    except Exception as e:
        print(f"[orchestrator] ⚠ couldn't stage approval for {fn_name}: {e}")
        return None

def _allowed_external_tools(permissions: dict | None) -> set[str]:
    """Compute the full external-mode tool allowlist for a given permission set."""
    allowed = set(EXTERNAL_DEFAULT_ALLOWED)
    if not permissions:
        return allowed
    for key, tools in EXTERNAL_PERMISSION_GATES.items():
        if permissions.get(key) and tools:
            allowed |= tools
    return allowed

def _filter_tools_by_allowlist(tools: list[dict], allowed: set[str]) -> list[dict]:
    """Drop tool defs whose names are not in the allowlist."""
    return [t for t in tools if t.get("name") in allowed]

# Some OpenAI-compatible models (notably DeepSeek-v3 over OpenRouter)
# intermittently emit tool calls as plain text in their native template
# instead of structured `tool_calls`. When that happens the OpenAI SDK
# reports no tool_calls and the raw template leaks to the user as the
# "answer" — so nothing executes. This recovers those calls.
#
# DeepSeek's template (both the unicode ｜▁ glyphs and ASCII fallbacks
# seen in the wild):
#   <｜tool▁calls▁begin｜><｜tool▁call▁begin｜>function<｜tool▁sep｜>NAME
#   ```json
#   {…args…}
#   ```<｜tool▁call▁end｜>…<｜tool▁calls▁end｜>
_TEXT_TOOLCALL_SENTINELS = ("tool▁calls▁begin", "tool_calls_begin")
# Locates each per-call header up to (and including) the tool name. The
# JSON args that follow are extracted with a balanced-brace scan so
# nested objects (e.g. data={"metadata": {...}}) aren't truncated.
_TEXT_TOOLCALL_HEAD_RE = re.compile(
    r"tool[▁_]call[▁_]begin[｜|<>]*"         # per-call opener (glyphs vary)
    r"\s*function\s*"
    r"[｜|<>]*tool[▁_]sep[｜|<>]*"           # name separator, bracketed
    r"\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)",  # tool name
    re.DOTALL,
)

def _scan_balanced_json(text: str, start: int) -> tuple[dict | None, int]:
    """From the first '{' at/after `start`, return (parsed_object, end_index)
    for the smallest balanced-brace span that parses as a JSON object.
    Returns (None, start) if none found. Brace counting ignores braces
    inside strings."""
    open_idx = text.find("{", start)
    if open_idx == -1:
        return None, start
    depth = 0
    in_str = False
    escape = False
    for i in range(open_idx, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = text[open_idx : i + 1]
                try:
                    obj = json.loads(blob)
                except Exception:
                    return None, i + 1
                return (obj if isinstance(obj, dict) else None), i + 1
    return None, len(text)

def _parse_text_tool_calls(raw_text: str) -> list[dict] | None:
    """Recover tool calls a model emitted as plain text instead of as
    structured `tool_calls`. Returns the same shape the providers use
    (``[{"id", "name", "arguments": dict}]``) or ``None`` if the text
    carries no recognizable tool-call markers."""
    if not raw_text or not any(s in raw_text for s in _TEXT_TOOLCALL_SENTINELS):
        return None
    calls: list[dict] = []
    for m in _TEXT_TOOLCALL_HEAD_RE.finditer(raw_text):
        name = m.group("name")
        args, _ = _scan_balanced_json(raw_text, m.end())
        if args is None:
            continue
        calls.append({"id": f"text_{uuid.uuid4().hex[:24]}", "name": name, "arguments": args})
    return calls or None

def _sanitize_json_schema(schema):
    """Make a JSON Schema safe for strict function-calling backends (Gemini
    via OpenRouter rejects the whole request otherwise).

    - Every ``type: "array"`` MUST declare ``items`` — default to a permissive
      string item when missing.
    - Strip ``$defs`` / ``definitions`` / ``$ref`` (Gemini can't resolve
      cross-references in tool schemas; the ``CompetitorInput`` error).
    Recurses through nested ``properties`` and ``items``."""
    if not isinstance(schema, dict):
        return schema
    out: dict = {}
    for k, v in schema.items():
        if k in ("$defs", "definitions", "$ref", "$schema"):
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: _sanitize_json_schema(pv) for pk, pv in v.items()}
        elif k == "items":
            out[k] = _sanitize_json_schema(v)
        elif isinstance(v, dict):
            out[k] = _sanitize_json_schema(v)
        else:
            out[k] = v
    if out.get("type") == "array" and "items" not in out:
        out["items"] = {"type": "string"}
    return out

# =====================================================================
# LLM Provider Abstraction
# =====================================================================

class ThinkTagParser:
    """
    Stateful parser that separates <think>...</think> blocks from visible text.

    Feed it text chunks via `feed(chunk)` — it yields (type, text) tuples where
    type is either "thinking" or "text". Handles tags split across chunks
    (e.g. chunk ends with "<thi" and next chunk starts with "nk>").
    """

    def __init__(self):
        self._inside_think = False
        self._buffer = ""  # holds partial tag matches

    @staticmethod
    def _find_partial_suffix(text: str, tag: str) -> int:
        """Return length of the longest suffix of `text` that is a prefix of `tag`, or 0."""
        for i in range(min(len(text), len(tag) - 1), 0, -1):
            if text.endswith(tag[:i]):
                return i
        return 0

    def feed(self, chunk: str):
        """Yield (event_type, text) tuples for each segment of the chunk."""
        self._buffer += chunk

        while self._buffer:
            if self._inside_think:
                close_idx = self._buffer.find("</think>")
                if close_idx != -1:
                    before = self._buffer[:close_idx]
                    if before:
                        yield ("thinking", before)
                    self._buffer = self._buffer[close_idx + len("</think>"):]
                    self._inside_think = False
                else:
                    # Check if buffer ends with a partial "</think>"
                    partial = self._find_partial_suffix(self._buffer, "</think>")
                    if partial:
                        safe = self._buffer[:-partial]
                        if safe:
                            yield ("thinking", safe)
                        self._buffer = self._buffer[-partial:]
                        return  # wait for more data
                    yield ("thinking", self._buffer)
                    self._buffer = ""
            else:
                open_idx = self._buffer.find("<think>")
                if open_idx != -1:
                    before = self._buffer[:open_idx]
                    if before:
                        yield ("text", before)
                    self._buffer = self._buffer[open_idx + len("<think>"):]
                    self._inside_think = True
                else:
                    partial = self._find_partial_suffix(self._buffer, "<think>")
                    if partial:
                        safe = self._buffer[:-partial]
                        if safe:
                            yield ("text", safe)
                        self._buffer = self._buffer[-partial:]
                        return  # wait for more data
                    yield ("text", self._buffer)
                    self._buffer = ""

    def flush(self):
        """Flush any remaining buffer content (call at end of stream)."""
        if self._buffer:
            etype = "thinking" if self._inside_think else "text"
            yield (etype, self._buffer)
            self._buffer = ""

def strip_think_tags(text: str) -> str:
    """Remove all <think>...</think> blocks from a string (for non-streaming paths).

    Also strips a dangling, unclosed <think> (model emitted reasoning but
    never closed the tag before the answer / before the turn was cut off) —
    its content is internal and must never reach the user."""
    import re
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Drop any remaining unclosed <think> through end-of-string.
    cleaned = re.sub(r"<think>.*\Z", "", cleaned, flags=re.DOTALL)
    return cleaned.strip()

class LLMProvider:
    """Base class for LLM providers."""

    def chat_with_tools(
        self, messages: list[dict], tools: list[dict]
    ) -> tuple[str | None, list[dict] | None]:
        """
        Send messages to the LLM with tool definitions.

        Returns:
            (text_response, tool_calls)
            - If tool_calls is None, text_response is the final answer.
            - If tool_calls is not None, execute them and loop back.
              Each tool_call is {"id": str, "name": str, "arguments": dict}
        """
        raise NotImplementedError

    def chat_with_tools_stream(self, messages: list[dict], tools: list[dict]):
        """
        Streaming variant: yields dict events as tokens arrive.

        Event shapes yielded:
          {"type": "text", "delta": "..."}             — a text token
          {"type": "thinking", "delta": "..."}         — a reasoning token (only on
                                                          models that expose one)
          {"type": "tool_call_start", "id": "x",
           "name": "..."}                              — beginning of a tool call
          {"type": "tool_call_args", "id": "x",
           "args_delta": "..."}                        — streaming JSON args chunk
          {"type": "tool_call_end", "id": "x",
           "name": "...", "arguments": {...}}          — tool call fully assembled
          {"type": "turn_done", "text": "full text",
           "tool_calls": [{id,name,arguments}, ...]}   — end of this provider turn

        This is a sync generator; orchestrator bridges it to async via a queue.
        """
        raise NotImplementedError

    def build_tool_result_message(self, tool_call_id: str, result: str) -> dict:
        raise NotImplementedError

    def build_assistant_tool_message(self, content, tool_calls) -> dict:
        raise NotImplementedError

class OpenAIProvider(LLMProvider):
    """OpenAI GPT models with function calling."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        default_headers: dict | None = None,
    ):
        from openai import OpenAI
        kwargs = {}
        headers: dict = {}
        if base_url:
            kwargs["base_url"] = base_url
            # Bypass Cloudflare WAF bot blocking if using a custom mapped domain
            headers["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) width/1920"
            )
        if default_headers:
            headers.update(default_headers)
        if headers:
            kwargs["default_headers"] = headers

        # Some API gateways reject empty Bearer tokens
        safe_api_key = api_key or config.OPENAI_API_KEY or "dummy-key"
        self._client = OpenAI(api_key=safe_api_key, **kwargs)
        self._model = model or config.OPENAI_MODEL

    def chat_with_tools(self, messages, tools):
        openai_tools = self._convert_tools(tools)

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=openai_tools if openai_tools else None,
            tool_choice="auto",
        )

        choice = response.choices[0]

        # Return RAW text with <think> tags intact. The orchestrator stores
        # this in conversation history so the model can see its own prior
        # reasoning on subsequent turns. The user-facing `reply` is stripped
        # by the orchestrator before returning to the client.
        if not choice.message.tool_calls:
            content = choice.message.content or ""
            # Recover tool calls a quirky model emitted as plain text rather
            # than as structured tool_calls (see _parse_text_tool_calls).
            recovered = _parse_text_tool_calls(content)
            if recovered:
                return "", recovered
            return content, None

        tool_calls = [
            {
                "id": tc.id,
                "name": tc.function.name,
                "arguments": json.loads(tc.function.arguments),
            }
            for tc in choice.message.tool_calls
        ]
        return choice.message.content or "", tool_calls

    def chat_with_tools_stream(self, messages, tools):
        """
        Stream an OpenAI (or OpenAI-compatible) completion. Yields text,
        thinking (if the provider exposes `reasoning_content`), and tool
        call events. Tool calls arrive in fragments indexed by position —
        we accumulate them and emit tool_call_end once the JSON args parse.
        """
        openai_tools = self._convert_tools(tools)

        stream = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=openai_tools if openai_tools else None,
            tool_choice="auto",
            stream=True,
        )

        # Accumulators across the stream.
        # raw_text_parts   = EVERYTHING the model produced, including thinking
        #                    wrapped in <think>...</think> tags. Stored in
        #                    conversation history so the model sees its own
        #                    prior reasoning on future turns.
        # The parser additionally routes segments to "text" vs "thinking"
        # events for the frontend UI — but for history we keep raw.
        raw_text_parts: list[str] = []
        think_parser = ThinkTagParser()
        # tool_calls keyed by index — OpenAI streams fragments per index:
        #   index 0: id + name + args chunk, then more args chunks, ...
        #   index 1: another call's id + name + args chunks, ...
        pending_tools: dict[int, dict] = {}
        started_tool_ids: set[str] = set()  # to emit tool_call_start only once per id

        def _get_attr(obj, name, default=None):
            # OpenAI SDK returns Pydantic models; compat providers sometimes
            # return plain dicts. Handle both without crashing.
            if obj is None:
                return default
            if isinstance(obj, dict):
                return obj.get(name, default)
            return getattr(obj, name, default)

        for chunk in stream:
            choices = _get_attr(chunk, "choices") or []
            if not choices:
                continue
            choice0 = choices[0]
            delta = _get_attr(choice0, "delta")
            if delta is None:
                continue

            # Text delta — route through <think> tag parser for UI events,
            # but ALSO keep the raw piece for history.
            text_piece = _get_attr(delta, "content")
            if text_piece:
                raw_text_parts.append(text_piece)
                for etype, segment in think_parser.feed(text_piece):
                    if etype == "text":
                        yield {"type": "text", "delta": segment}
                    else:
                        yield {"type": "thinking", "delta": segment}

            # Native thinking / reasoning delta (best-effort across compat providers)
            # Wrap in <think>...</think> when adding to raw so history round-trips.
            for k in ("reasoning_content", "thinking", "reasoning"):
                think_piece = _get_attr(delta, k)
                if think_piece:
                    raw_text_parts.append(f"<think>{think_piece}</think>")
                    yield {"type": "thinking", "delta": think_piece}
                    break

            # Tool call fragments
            tcs = _get_attr(delta, "tool_calls") or []
            for tc in tcs:
                idx = _get_attr(tc, "index", 0) or 0
                tc_id = _get_attr(tc, "id")
                fn = _get_attr(tc, "function")
                fn_name = _get_attr(fn, "name")
                fn_args_delta = _get_attr(fn, "arguments")

                slot = pending_tools.setdefault(idx, {
                    "id": None,
                    "name": None,
                    "arguments_text": "",
                })
                if tc_id and not slot["id"]:
                    slot["id"] = tc_id
                if fn_name and not slot["name"]:
                    slot["name"] = fn_name

                # Emit tool_call_start the first time we have both id and name
                if slot["id"] and slot["name"] and slot["id"] not in started_tool_ids:
                    started_tool_ids.add(slot["id"])
                    yield {
                        "type": "tool_call_start",
                        "id": slot["id"],
                        "name": slot["name"],
                    }

                if fn_args_delta:
                    slot["arguments_text"] += fn_args_delta
                    if slot["id"]:
                        yield {
                            "type": "tool_call_args",
                            "id": slot["id"],
                            "args_delta": fn_args_delta,
                        }

            finish = _get_attr(choice0, "finish_reason")
            if finish == "tool_calls":
                # End-of-turn with tool calls. Parse each slot's args.
                break
            if finish == "stop":
                break

        # Flush any remaining content in the think-tag parser
        for etype, segment in think_parser.flush():
            if etype == "text":
                yield {"type": "text", "delta": segment}
            else:
                yield {"type": "thinking", "delta": segment}

        # Finalize any accumulated tool calls.
        final_tool_calls = []
        for idx in sorted(pending_tools.keys()):
            slot = pending_tools[idx]
            if not (slot["id"] and slot["name"]):
                continue
            try:
                args = json.loads(slot["arguments_text"]) if slot["arguments_text"] else {}
            except Exception:
                args = {}
            final_tool_calls.append({
                "id": slot["id"],
                "name": slot["name"],
                "arguments": args,
            })
            yield {
                "type": "tool_call_end",
                "id": slot["id"],
                "name": slot["name"],
                "arguments": args,
            }

        raw_text = "".join(raw_text_parts)

        # No structured tool calls? A quirky model may have streamed the
        # call as plain text instead (see _parse_text_tool_calls). Recover
        # it and emit the start/end events the frontend expects. The leaked
        # template text already streamed as `text`, but turn_tool_calls
        # being non-empty makes the orchestrator fire `text_to_thinking`,
        # moving it out of the answer bubble.
        if not final_tool_calls:
            recovered = _parse_text_tool_calls(raw_text)
            if recovered:
                for tc in recovered:
                    yield {"type": "tool_call_start", "id": tc["id"], "name": tc["name"]}
                    yield {
                        "type": "tool_call_end",
                        "id": tc["id"],
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                    }
                final_tool_calls = recovered

        yield {
            "type": "turn_done",
            # RAW text (with <think> tags) — orchestrator stores this in
            # history and strips for the user-facing reply.
            "text": raw_text,
            "tool_calls": final_tool_calls if final_tool_calls else None,
        }

    @staticmethod
    def _convert_tools(tools: list[dict]) -> list[dict]:
        """Convert our generic tool format to OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": _sanitize_json_schema({
                        "type": "object",
                        "properties": t["properties"],
                        "required": t.get("required", []),
                    }),
                },
            }
            for t in tools
        ]

    def build_tool_result_message(self, tool_call_id: str, result: str) -> dict:
        return {"role": "tool", "tool_call_id": tool_call_id, "content": result}

    def build_assistant_tool_message(self, content, tool_calls):
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"]),
                    },
                }
                for tc in tool_calls
            ],
        }

class GeminiProvider(LLMProvider):
    """Google Gemini models with function calling."""

    def __init__(self):
        from google import genai
        from google.genai import types
        self._genai = genai
        self._types = types
        self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        self._model = config.GEMINI_MODEL

    def chat_with_tools(self, messages, tools):
        types = self._types

        # Convert our generic tools into Gemini FunctionDeclaration format
        gemini_tools = self._convert_tools(tools)

        # Convert messages to Gemini Content format
        contents = self._convert_messages(messages)

        gen_config = None
        if gemini_tools:
            gen_config = types.GenerateContentConfig(
                tools=[types.Tool(function_declarations=gemini_tools)],
            )

        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=gen_config,
        )

        # Return RAW text with <think> tags intact. Orchestrator stores this
        # in history so the model sees its own past reasoning. User-facing
        # reply gets stripped by the orchestrator before returning.
        candidate = response.candidates[0] if response.candidates else None
        if not candidate:
            return response.text or "", None

        # Collect function calls from all parts. For native thinking parts
        # (Gemini 2.5 Flash with `part.thought=True`), wrap the text in
        # <think>...</think> so it round-trips through our tag-based memory.
        #
        # Gemini 3 Flash + thinking REQUIRES the model's `thought_signature`
        # to be echoed back on the function_call Part when we feed history
        # in for the next turn — otherwise the API rejects the request with
        # 400 INVALID_ARGUMENT (see docs.gemini-api/thought-signatures).
        # We capture it here and round-trip via _convert_messages below.
        function_calls = []
        text_parts = []
        for part in candidate.content.parts:
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                tc: dict = {
                    "id": fc.id if hasattr(fc, "id") else str(uuid.uuid4()),
                    "name": fc.name,
                    "arguments": dict(fc.args) if fc.args else {},
                }
                ts = getattr(part, "thought_signature", None)
                if ts:
                    tc["_thought_signature"] = ts
                function_calls.append(tc)
            elif hasattr(part, "text") and part.text:
                if getattr(part, "thought", False):
                    text_parts.append(f"<think>{part.text}</think>")
                else:
                    text_parts.append(part.text)

        if function_calls:
            joined = "\n".join(text_parts) if text_parts else None
            return joined, function_calls

        return response.text or "", None

    def chat_with_tools_stream(self, messages, tools):
        """
        Stream a Gemini completion. Gemini streams text deltas via parts;
        function_calls usually arrive as a single part (not fragmented),
        so we emit tool_call_end directly when we see one.
        """
        types = self._types
        gemini_tools = self._convert_tools(tools)
        contents = self._convert_messages(messages)

        gen_config = None
        if gemini_tools:
            gen_config = types.GenerateContentConfig(
                tools=[types.Tool(function_declarations=gemini_tools)],
            )

        stream = self._client.models.generate_content_stream(
            model=self._model,
            contents=contents,
            config=gen_config,
        )

        # raw_text_parts accumulates the FULL model output (including any
        # thinking wrapped in <think> tags) for storage in history so the
        # model can see its own reasoning on subsequent turns.
        raw_text_parts: list[str] = []
        tool_calls: list[dict] = []
        think_parser = ThinkTagParser()

        for chunk in stream:
            candidates = getattr(chunk, "candidates", None) or []
            if not candidates:
                continue
            cand = candidates[0]
            content = getattr(cand, "content", None)
            if content is None:
                continue
            parts = getattr(content, "parts", None) or []
            for part in parts:
                fc = getattr(part, "function_call", None)
                if fc:
                    tc_id = getattr(fc, "id", None) or str(uuid.uuid4())
                    name = getattr(fc, "name", "") or ""
                    args_raw = getattr(fc, "args", None)
                    args = dict(args_raw) if args_raw else {}
                    tc: dict = {"id": tc_id, "name": name, "arguments": args}
                    # Gemini 3 + thinking attaches a thought_signature to
                    # function_call parts. Capture it so _convert_messages
                    # can echo it back on the next turn — otherwise Gemini
                    # rejects the request (400 INVALID_ARGUMENT, see
                    # https://ai.google.dev/gemini-api/docs/thought-signatures).
                    ts = getattr(part, "thought_signature", None)
                    if ts:
                        tc["_thought_signature"] = ts
                    tool_calls.append(tc)
                    yield {"type": "tool_call_start", "id": tc_id, "name": name}
                    yield {
                        "type": "tool_call_end",
                        "id": tc_id,
                        "name": name,
                        "arguments": args,
                    }
                    continue

                # Native thinking parts (Gemini 2.5 Flash etc.)
                is_thought = getattr(part, "thought", False)
                text_piece = getattr(part, "text", None)
                if text_piece:
                    if is_thought:
                        # Native thinking — wrap in tags for history, emit as thinking for UI
                        raw_text_parts.append(f"<think>{text_piece}</think>")
                        yield {"type": "thinking", "delta": text_piece}
                    else:
                        # Regular text — keep raw for history, split for UI
                        raw_text_parts.append(text_piece)
                        for etype, segment in think_parser.feed(text_piece):
                            if etype == "text":
                                yield {"type": "text", "delta": segment}
                            else:
                                yield {"type": "thinking", "delta": segment}

        # Flush remaining parser buffer (UI only; raw was already captured)
        for etype, segment in think_parser.flush():
            if etype == "text":
                yield {"type": "text", "delta": segment}
            else:
                yield {"type": "thinking", "delta": segment}

        yield {
            "type": "turn_done",
            # RAW text (with <think> tags) — orchestrator stores this in
            # history and strips for the user-facing reply.
            "text": "".join(raw_text_parts),
            "tool_calls": tool_calls or None,
        }

    def _convert_tools(self, tools: list[dict]) -> list:
        """Convert to Gemini FunctionDeclaration format."""
        types = self._types
        declarations = []

        for t in tools:
            schema_props = {}
            for pname, pinfo in t.get("properties", {}).items():
                ptype = pinfo.get("type", "string").upper()
                type_map = {
                    "STRING": "STRING", "INTEGER": "INTEGER", "NUMBER": "NUMBER",
                    "BOOLEAN": "BOOLEAN", "ARRAY": "ARRAY", "OBJECT": "OBJECT",
                    "STR": "STRING", "INT": "INTEGER", "FLOAT": "NUMBER", "BOOL": "BOOLEAN",
                }
                gemini_type = type_map.get(ptype, "STRING")
                kwargs = {
                    "type": gemini_type,
                    "description": pinfo.get("description", ""),
                }
                if gemini_type == "ARRAY":
                    kwargs["items"] = types.Schema(type="STRING")
                    
                schema_props[pname] = types.Schema(**kwargs)

            declarations.append(
                types.FunctionDeclaration(
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters=types.Schema(
                        type="OBJECT",
                        properties=schema_props,
                        required=t.get("required", []),
                    ),
                )
            )

        return declarations

    @staticmethod
    def _convert_messages(messages: list[dict]) -> list:
        """
        Convert OpenAI-style messages to Gemini Contents.

        Key fix: tool results are sent as FunctionResponse parts
        so Gemini understands the tool already executed and won't
        re-call it.
        """
        from google.genai import types
        contents = []

        for msg in messages:
            role = msg["role"]

            if role == "system":
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=f"[System Instructions]\n{msg['content']}")]
                ))
            elif role == "user":
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=msg["content"])]
                ))
            elif role == "assistant":
                # Check if this assistant message had tool calls
                if "tool_calls" in msg and msg["tool_calls"]:
                    parts = []
                    if msg.get("content"):
                        parts.append(types.Part.from_text(text=msg["content"]))
                    for tc in msg["tool_calls"]:
                        fc_part = types.Part.from_function_call(
                            name=tc["name"],
                            args=tc.get("arguments", {}),
                        )
                        # Gemini 3 + thinking REQUIRES the model's original
                        # thought_signature to ride along on the function_call
                        # Part when echoed back. Captured at read time and
                        # passed through here. Older / non-thinking models
                        # leave _thought_signature unset, which is harmless.
                        ts = tc.get("_thought_signature")
                        if ts:
                            fc_part.thought_signature = ts
                        parts.append(fc_part)
                    contents.append(types.Content(role="model", parts=parts))
                else:
                    contents.append(types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=msg.get("content", ""))]
                    ))
            elif role == "tool":
                # Send as FunctionResponse so Gemini knows the tool executed
                tool_call_id = msg.get("tool_call_id", "")
                # Find the tool name from the previous assistant message
                tool_name = msg.get("_tool_name", "unknown")
                try:
                    parsed = json.loads(msg["content"])
                    # FunctionResponse.response MUST be a dict, never a list/str
                    result_data = parsed if isinstance(parsed, dict) else {"result": parsed}
                except (json.JSONDecodeError, KeyError):
                    result_data = {"result": msg.get("content", "")}

                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_function_response(
                        name=tool_name,
                        response=result_data,
                    )]
                ))

        return contents

    def build_tool_result_message(self, tool_call_id: str, result: str, tool_name: str = "unknown") -> dict:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result,
            "_tool_name": tool_name,  # Extra field for Gemini FunctionResponse
        }

    def build_assistant_tool_message(self, content, tool_calls):
        return {
            "role": "assistant",
            "content": content or "",
            "tool_calls": tool_calls,
        }

def _get_provider() -> LLMProvider:
    """Get the configured LLM provider."""
    provider_name = config.LLM_PROVIDER.lower()
    if provider_name == "gemini":
        return GeminiProvider()
    elif provider_name == "openrouter":
        return OpenAIProvider(
            base_url=config.OPENROUTER_BASE_URL,
            api_key=config.OPENROUTER_API_KEY,
            model=config.OPENROUTER_MODEL,
            default_headers={
                "HTTP-Referer": config.FRONTEND_URL or "https://persona.zynd.ai",
                "X-Title": "Zynd",
            },
        )
    elif provider_name == "custom":
        return OpenAIProvider(
            base_url=config.CUSTOM_LLM_BASE_URL,
            api_key=config.CUSTOM_LLM_API_KEY,
            model=config.CUSTOM_LLM_MODEL,
        )
    else:
        return OpenAIProvider()

# =====================================================================
# Tool conversion from ContextAware → generic format
# =====================================================================

def _capabilities_to_generic_tools() -> list[dict]:
    """
    Convert ContextAware capabilities to a generic tool format
    that both OpenAI and Gemini providers can consume.
    """
    caps = mcp_server.get_capabilities()
    tools = []

    for tool in caps["tools"]:
        properties = {}
        required = []

        for param in tool["parameters"]:
            # Normalize type string and convert Python type names to JSON Schema types
            ptype = str(param.get("type", "string")).lower()
            type_map = {
                "str": "string",
                "string": "string",
                "int": "integer",
                "integer": "integer",
                "float": "number",
                "number": "number",
                "bool": "boolean",
                "boolean": "boolean",
                "list": "array",
                "array": "array",
                "dict": "object",
                "object": "object",
                "none": "string",
                "nonetype": "string",
                "union": "string",
                "any": "string"
            }
            ptype = type_map.get(ptype, "string")

            prop: dict = {"type": ptype}
            if "description" in param:
                prop["description"] = param["description"]
            if "default" in param:
                prop["default"] = param["default"]

            properties[param["name"]] = prop
            if param.get("required", False):
                required.append(param["name"])

        tools.append({
            "name": tool["name"],
            "description": tool.get("description", ""),
            "properties": properties,
            "required": required,
        })

    return tools

# =====================================================================
# Main orchestration loop
# =====================================================================

_BRIEF_DOC_CACHE: dict[str, tuple[float, str]] = {}
_BRIEF_DOC_CACHE_TTL_SECONDS = 60

def _fetch_brief_doc_content(user_id: str, doc_id: str) -> str | None:
    """
    Fetch the brief Google Doc body, with a short in-process cache so the
    Docs API isn't hit on every chat turn. Returns None on any failure
    (caller falls back to persona.description).
    """
    import time
    cached = _BRIEF_DOC_CACHE.get(doc_id)
    now = time.time()
    if cached and now - cached[0] < _BRIEF_DOC_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        from mcp.tools.google.docs import read_document
        result = read_document(user_id=user_id, document_id=doc_id)
        if result.get("success"):
            content = (result.get("content") or "").strip()
            _BRIEF_DOC_CACHE[doc_id] = (now, content)
            return content
    except Exception as e:
        print(f"[orchestrator] brief doc fetch failed for {doc_id}: {e}")
    return None

def _format_user_brief(
    persona: dict,
    redact_profile: bool = False,
    redact_brief: bool = False,
    user_id: str | None = None,
) -> str:
    """
    Render the principal's profile/description as a 'who you serve' briefing.

    Source priority:
      1. The persona's brief Google Doc, if `brief_doc_id` is set, we can
         fetch it, AND ``redact_brief`` is False. This is the long-form
         context the user maintains in the dashboard's Brief tab.
      2. Fall back to ``persona.description`` (the short pitch — always
         shareable because it's already on the public registry card).

    Flags
    -----
    redact_profile
        Strip profile fields (title, org, location, interests, links).
        Used in external mode when ``can_view_full_profile`` isn't granted.
    redact_brief
        Skip the brief Google Doc body entirely; the prompt sees only the
        short ``persona.description``. Used by group dispatch when the
        asker doesn't have ``can_see_brief`` permission on the group, so
        the brief body never lands in the LLM's context window for that
        turn — defense-in-depth, not just a behavioral hint.
    """
    brief_doc_id = persona.get("brief_doc_id")
    doc_content = None
    if brief_doc_id and user_id and not redact_brief:
        doc_content = _fetch_brief_doc_content(user_id, brief_doc_id)

    desc = (doc_content or persona.get("description") or "").strip()
    profile = persona.get("profile") or {}

    lines = []
    if desc:
        lines.append(desc)

    if redact_profile:
        return "\n".join(lines) if lines else "(no profile details set yet)"

    profile_lines = []
    if profile.get("title"):
        profile_lines.append(f"- Title: {profile['title']}")
    if profile.get("organization"):
        profile_lines.append(f"- Organization: {profile['organization']}")
    if profile.get("location"):
        profile_lines.append(f"- Location: {profile['location']}")
    interests = profile.get("interests")
    if interests:
        if isinstance(interests, list):
            interests = ", ".join(interests)
        profile_lines.append(f"- Interests: {interests}")
    socials = []
    for key in ("twitter", "linkedin", "github", "website"):
        if profile.get(key):
            socials.append(f"{key}: {profile[key]}")
    if socials:
        profile_lines.append(f"- Links: {' | '.join(socials)}")

    if profile_lines:
        if lines:
            lines.append("")
        lines.extend(profile_lines)

    return "\n".join(lines) if lines else "(no profile details set yet)"

def _get_user_email(user_id: str) -> str | None:
    """Fetch the user's email from Supabase auth.users via admin API."""
    try:
        import requests
        headers = {
            "apikey": config.SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        }
        r = requests.get(
            f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{user_id}",
            headers=headers,
            timeout=4,
        )
        if not r.ok:
            return None
        data = r.json()
        return data.get("email") or (data.get("user_metadata") or {}).get("email")
    except Exception:
        return None


def _build_system_prompt(
    user_id: str,
    connected_providers: list[str],
    is_external: bool = False,
    sender_agent_id: str | None = None,
    external_permissions: dict | None = None,
    time_zone: str | None = None,
    is_group_context: bool = False,
    surface: str = "web",
    linkedin_scraped: bool = False,
    memory_context_str: str = "",
    style_context_str: str = "",
) -> str:
    """Build a system prompt that tells the agent what it can do.

    `surface` is the channel the reply will render on: "web" (the app, which
    renders service/agent results as rich cards) or anything else (e.g.
    "telegram", plain text — include the answer inline since there's no card).

    `linkedin_scraped` is True when the user has LinkedIn profile data via
    scraping (linkedin_profiles table), even if they haven't completed the
    OAuth flow (api_tokens table) for posting access.
    """
    tools_prompt = mcp_server.get_tools_prompt()

    parts: list[str] = []
    if connected_providers:
        parts.append(", ".join(connected_providers))
    has_linkedin_oauth = "linkedin" in connected_providers
    if linkedin_scraped and not has_linkedin_oauth:
        parts.append("linkedin (profile reading only)")
    providers_str = ", ".join(parts) if parts else "none"

    from agent.persona_manager import get_persona_status
    persona = get_persona_status(user_id)
    principal_name = persona.get("name", "the user")
    agent_handle = persona.get("agent_handle")  # may be None
    capabilities = persona.get("capabilities", [])

    # In external mode, redact profile fields if the foreign side doesn't
    # have can_view_full_profile. The principal's name and description are
    # always visible (those are already on the public card), but title,
    # organization, location, interests and social links are gated.
    #
    # `can_see_brief` is a separate gate, defaulting to True so existing
    # connections (which don't carry the flag) keep current behavior. Group
    # dispatch sets it explicitly to mirror the per-member toggle in the
    # group's settings — when False, the brief Google Doc body is dropped
    # entirely from the system prompt, not just behaviorally suppressed.
    perms_view = (external_permissions or {})
    # Group context: the persona is answering about its OWN principal, so it
    # always needs the full brief in context. Privacy is enforced by the
    # privacy_hint instruction injected by group_dispatch, not by stripping
    # the brief from the system prompt.
    redact = is_external and not is_group_context and not perms_view.get("can_view_full_profile", False)
    redact_brief = is_external and not is_group_context and perms_view.get("can_see_brief", True) is False
    user_brief = _format_user_brief(
        persona,
        redact_profile=redact,
        redact_brief=redact_brief,
        user_id=user_id,
    )

    # Fetch the principal's email — only for internal mode (principal chatting
    # with their own persona). Never expose it to external agents.
    if is_external:
        user_email = "(not shared in external mode)"
    else:
        user_email = _get_user_email(user_id) or "(not available)"

    # Time context — the LLM uses this to translate "let's meet at 2pm" into
    # the right wall-clock time for `create_calendar_event` etc. Internal-mode
    # callers (chat) supply the browser TZ; external/webhook callers don't,
    # so we fall back to a note that says "no TZ known, assume UTC".
    if time_zone:
        from datetime import datetime as _dt
        try:
            from zoneinfo import ZoneInfo
            now_local = _dt.now(ZoneInfo(time_zone)).strftime("%Y-%m-%d %H:%M %Z")
        except Exception:
            now_local = _dt.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        time_context = (
            f"Your principal's current timezone is `{time_zone}` (local time now: {now_local}).\n"
            f"When you call `create_calendar_event` (or any tool with a `time_zone` arg), pass "
            f"`time_zone=\"{time_zone}\"` so the event lands at the wall-clock time they meant. "
            f"When you read times back to your principal, present them in their local zone, "
            f"not UTC."
        )
    else:
        time_context = (
            "No browser timezone supplied — treat times as UTC and tell the principal "
            "explicitly when you do."
        )

    # ── Identity preamble — shared by both modes ─────────────────────
    # The agent has its OWN name (`agent_handle`) which is distinct from the
    # principal's name (`principal_name`, what the network sees). If the
    # principal didn't pick a name for the agent, the agent has no proper
    # name and refers to itself as "the AI agent representing X".
    if agent_handle:
        agent_self_intro = (
            f"You have your own name: '{agent_handle}'. This is YOUR name as the AI agent — "
            f"it is intentionally different from your principal's name so there is no confusion about "
            f"who is who. Your principal's name is '{principal_name}' — that is a separate person, the "
            f"human you represent. When you introduce yourself, use a phrasing like "
            f"\"I'm {agent_handle}, the AI agent representing {principal_name}\" — NEVER claim to be "
            f"{principal_name} yourself."
        )
    else:
        agent_self_intro = (
            f"You do not have a proper name of your own. Your principal is '{principal_name}'. "
            f"When you introduce yourself, use a phrasing like \"I'm the AI agent representing "
            f"{principal_name}\" — NEVER say \"I am {principal_name}\" as if you were them."
        )

    identity_preamble = f"""You are an autonomous AI agent on the Zynd AI Network.

{agent_self_intro}

You are NOT a human. You are NOT your principal. You are an AI agent that has been deployed by a human principal and you act on their behalf. Treat the principal as a third party — when you talk ABOUT them, use third person ("my principal", "they", "{principal_name}"). When you talk about yourself, use first person ("I", "me") and make it clear you are an AI agent.

## CRITICAL: Thinking vs. Response Format
You MUST separate your internal reasoning from your visible reply using think tags.

- Wrap ALL internal reasoning, planning, deliberation, and self-talk inside <think>...</think> tags.
- ONLY text OUTSIDE <think> tags is shown to the user. Everything inside is hidden.
- Your visible reply must be ONLY the clean, final answer — no meta-commentary, no "let me think about this", no reasoning traces.
- You may use multiple <think> blocks if needed (e.g. think → reply → think again → reply more).
- If you have nothing to reason about, skip the <think> block entirely and just reply.

Example:
<think>The user said "ey". This looks like a greeting. I should introduce myself as the agent.</think>
Hi! I'm {agent_handle or ("the AI agent representing " + principal_name)}, here to help. What can I do for you?

## Who Your Principal Is
The following is a briefing your principal ('{principal_name}') wrote about themselves so you can represent them accurately:

{user_brief}

Your principal's email address is: {user_email}

Use this as factual background about the human you serve. Do not adopt their identity, do not claim to be them, do not speak in their voice as if you are them. You are their agent, not them."""

    if is_external and is_group_context:
        perms = external_permissions or {}
        allowed_tools = _allowed_external_tools(perms)
        allowlist_block = ", ".join(sorted(allowed_tools)) or "(none)"
        can_propose_meeting = "propose_group_meeting" in allowed_tools
        can_check_calendar = "list_calendar_events" in allowed_tools

        if can_propose_meeting:
            scheduling_instruction = (
                "- When asked to schedule a meeting → call `propose_group_meeting(title, start_time, end_time, location?, description?, time_zone)`. "
                "The `group_id` and `user_id` are auto-injected — you do NOT pass them. "
                "If you can check the calendar (list_calendar_events), do that first to confirm the slot is free. "
                "Times must be ISO-8601 UTC for the tool call (e.g. \"2026-05-15T19:00:00Z\") — but ALWAYS pass `time_zone` "
                "as the ASKER's IANA tz from the `Current local time for the asker` line in this prompt "
                "(e.g. \"Asia/Kolkata\", \"America/New_York\"). The group's confirmation message renders in that zone. "
                "Calling this tool **stages an approval card on your principal's inbox** — it does NOT create the event yet. "
                "On your principal's approval, the event is created on their calendar with every other group member as an attendee, "
                "and a system message is posted to the group chat confirming the slot. "
                "After calling the tool, reply in one short sentence telling the asker the request was sent to your principal for confirmation. "
                "When you mention the time in your chat reply, use the ASKER's local wall-clock (e.g. \"3 PM tomorrow\" or \"Sat 3:00 PM\") — "
                "NEVER append a UTC time, NEVER write \"...Z\", NEVER show ISO-8601 in chat. UTC is for the tool call only, not for humans. "
                "NEVER call `create_calendar_event` directly in a group — that would silently write without consent. "
                "NEVER call `propose_meeting` in a group — that's for 1:1 DM threads only. "
                "NEVER claim the meeting is 'scheduled' or 'booked' before the principal has approved — say it's 'sent for confirmation' or 'pending your principal's approval'."
            )
        else:
            scheduling_instruction = (
                "- When asked to schedule a meeting → you do NOT have permission to schedule meetings in this group "
                "(the asker's `can_query_calendar` group permission is off). "
                "Say so in one short sentence and suggest the asker request that permission from the group owner. "
                "NEVER claim you 'scheduled', 'booked', 'staged', or 'queued' anything — you did not."
            )

        if can_check_calendar:
            calendar_instruction = (
                "- When asked to check calendar availability → call `list_calendar_events` NOW and report what you find. "
                "Use the current time from the Time Context to interpret \"today\", \"this week\", \"9 PM tonight\", etc."
            )
        else:
            calendar_instruction = (
                "- When asked to check calendar availability → you do NOT have permission to read the calendar in this group. "
                "Say so briefly and suggest the asker request 'can_query_calendar' from the group owner. "
                "Never invent availability."
            )

        if agent_handle:
            group_self_intro = (
                f"Your name is {agent_handle}. You are an AI agent representing {principal_name}. "
                f"You have been @-mentioned in a private group room and are replying on behalf of your principal."
            )
        else:
            group_self_intro = (
                f"You are an AI agent representing {principal_name}. "
                f"You have been @-mentioned in a private group room and are replying on behalf of your principal."
            )

        return f"""## Role
{group_self_intro}

You are NOT {principal_name}. You are their AI agent. Never impersonate the principal — speak as their representative, not as them personally.

## CRITICAL: Response Format
- **Start your reply directly with the answer.** Never open with "I'm the AI agent representing…", "As {principal_name}'s agent…", or any self-introduction. The UI already labels you as an AI persona — just answer.
- Wrap ALL internal reasoning inside <think>...</think> tags. Only text OUTSIDE those tags is shown to the group.

## About Your Principal
The following briefing was written by {principal_name} about themselves. Use it as the authoritative source when answering questions about them.

{user_brief}

## Context: Private Group Room
This is a private, invitation-only group room. Everyone in this room was explicitly added by the group owner. You have full trust — act on requests directly.

## How to Respond

**You are an action-taker, not just an information-giver.**

- When asked about your principal → answer directly from the brief above. 1–3 sentences, specific.
{calendar_instruction}
{scheduling_instruction}
- When asked a question that requires tool use → use the tool, then answer. Never say "I don't have permission" if the tool is in your allowed list. NEVER claim you used a tool that is NOT in the allowed-tools list below — if a tool isn't listed, you don't have it, and pretending you called it is a hallucination.

**Tone:** Direct and confident. You're an active team member, not a passive relay. Complete the task in the reply.

## What NOT to Do
- NEVER open with a self-introduction ("I'm the AI agent for X", "As X's agent…").
- NEVER say "you should confirm directly with {principal_name}" when you have calendar access — you ARE their representative, act on their behalf.
- NEVER say "I don't have permission to check the time" — use `get_current_time` or the time context provided.
- NEVER say "I'll pass this along" or "they'll follow up" — if a tool can handle it, use it.
- NEVER do persona discovery here (`search_zynd_personas`, `get_persona_profile`) — this is a private group room, not a place to surface other agents.
- You MAY use Zynd *services* (`search_zynd_services` → `get_zynd_service_card` → `call_zynd_service`) when the group asks for a capability you don't have built in (translation, file conversion, summarization, currency, etc.). Always go search → card → call in order; read `input_schema` to decide whether to pass `text=` or `data=`. Lead replies with the answer, not with "I used a service".
- NEVER use the words "staged", "queued for approval", "scheduled", "booked", "created the ticket", "sent the invite", or any equivalent confirmation phrasing UNLESS you actually invoked a tool on this turn that returned success. If the tool wasn't called (because it's not in your allowed list, or you chose not to call it), do NOT pretend the action happened. State plainly that you can't do it and why.

## Allowed Tools (this thread)
{allowlist_block if allowlist_block != "(none)" else "No tools available on this thread."}

When calling any tool, always pass `user_id` as "{user_id}".

## Current Time Context
{time_context}

## Available Tools
{tools_prompt}
"""

    if is_external:
        good_intro = (
            f"\"Hi, I'm {agent_handle}, the AI agent representing {principal_name}. "
            f"They're currently focused on X. Would you like me to pass a message along?\""
            if agent_handle else
            f"\"Hi, I'm the AI agent representing {principal_name}. They're currently focused on X. "
            f"Would you like me to pass a message along?\""
        )

        # ── Per-thread permission allowlist ──
        # The principal sets per-connection permissions in the connection
        # settings drawer. We render the active set in human-readable form
        # AND show the resulting tool allowlist so the LLM has zero ambiguity
        # about what's permitted on this specific thread.
        perms = external_permissions or {}
        allowed_tools = _allowed_external_tools(perms)
        permission_lines = []
        permission_lines.append(
            f"- Request meetings:        {'✅ allowed' if perms.get('can_request_meetings') else '🚫 forbidden'}"
        )
        permission_lines.append(
            f"- Query my availability:   {'✅ allowed' if perms.get('can_query_availability') else '🚫 forbidden — refuse calendar look-ups'}"
        )
        permission_lines.append(
            f"- View my full profile:    {'✅ allowed' if perms.get('can_view_full_profile') else '🚫 forbidden — only the public name + description above are shareable'}"
        )
        permission_lines.append(
            f"- Post / act on accounts:  {'✅ allowed' if perms.get('can_post_on_my_behalf') else '🚫 forbidden — refuse any write/post/send action'}"
        )
        permission_block = "\n".join(permission_lines)
        allowlist_block = ", ".join(sorted(allowed_tools)) or "(none)"

        return f"""{identity_preamble}

## Current Conversation
You are currently being contacted by ANOTHER AGENT on the Zynd Network: `{sender_agent_id}`. This is not your principal — this is an external party messaging your principal's public-facing agent (you). Your job is to respond professionally on your principal's behalf.

When you reply, you are speaking AS THE AGENT, not as the principal. Examples:
  - GOOD: {good_intro}
  - GOOD: "On behalf of {principal_name}, I can confirm they're interested in Y."
  - BAD:  "Hi, I'm {principal_name}. I'm currently working on..."  ← do NOT impersonate {principal_name}
  - BAD:  "Yes, I built that project."  ← {principal_name} built it, not you

## Connection Permissions for This Thread
Your principal has granted this specific connection the following permissions:

{permission_block}

The ONLY tools you may call on this thread are:
  {allowlist_block}

If the foreign agent asks for anything outside that list — calendar reads, posts, edits, or any private data not in the briefing above — politely refuse and tell them the principal hasn't granted that permission. Do NOT try to call a forbidden tool; the request will be hard-blocked even if you do, and the refusal message you give matters.

## STRICT SECURITY BOUNDARY
- NEVER execute destructive actions.
- NEVER leak data the briefing above doesn't already include.
- Your principal's general capability list is: {capabilities}. The per-thread permissions above are STRICTER and override this — if a capability isn't allowed by the per-thread permissions, you cannot use it for this caller even if it's in the general list.

## Connected Accounts
Your principal has the following accounts connected: {providers_str}.

If "linkedin (profile reading only)" is listed, that means the principal's LinkedIn profile has been scraped and is available in your briefing — you can reference their posts, experience, and professional background. However, you CANNOT call `post_to_linkedin` because the OAuth posting token is not yet connected. If your principal asks you to post, tell them to connect LinkedIn OAuth from their dashboard settings.

## Current Time Context
{time_context}

## Available Tools
{tools_prompt}

## Meeting Proposals (external mode)
If the foreign agent is asking to schedule a meeting, and `propose_meeting` is in your allowlist above:
  - You MAY call `propose_meeting` to formally request a meeting with your principal. The proposal will create a ticket your principal sees in their inbox; they decide whether to accept, counter, or decline.
  - Be concrete about the requested time (ISO-8601 UTC) and include a clear title.
  - Do NOT try to accept or finalize a meeting yourself — only the principal can act on incoming proposals.
If `propose_meeting` is NOT in your allowlist, refuse any scheduling request politely, explaining that the principal has not granted this connection permission to request meetings.

## Conversation Pace (CRITICAL — read carefully)
You operate on a STRICT turn budget. After ~3 of your replies on this thread, the system inserts a halt note and you stop being run on this thread. So every reply must move things forward — no filler.

On EVERY turn, do exactly one of these:
  (a) **Act with a tool.** If `propose_meeting` is allowed and the request is to schedule, call it on this turn with concrete times. If they need profile info you can share, share it.
  (b) **Escalate to your principal.** When you can't act because you lack data, lack a permission, or the request needs human judgment, say so plainly. The exact phrasing is up to you, but the message must clearly indicate that you're handing this off to your human and they will follow up. Some natural ways: "I'll loop my principal in on this — they'll follow up directly", "Let me check with my person and circle back", "Passing this along to {principal_name}; they'll be in touch". Vary the phrasing — don't paste a canned line. Once you escalate, the system will mark the thread as needing your principal's attention and stop running you on it. This is the RIGHT outcome when you can't act.
  (c) **Ask ONE specific question** that, when answered, lets you do (a) on the next turn. Examples: "Which 30-minute window works — Tuesday 3pm UTC or Friday 10am UTC?" Never ask vague open questions like "when's good?"

Things you must NEVER do:
  - "Sounds good, I'll keep an eye out."
  - "Looking forward to hearing from you!"
  - "Have a great day!"
  - "I'll be in touch soon."
  - "Thank you for the response." as a standalone reply.
  - Any reply that's pure acknowledgment with no concrete next step.

These look polite but they burn turns and produce no outcome. They are FORBIDDEN as standalone replies. If you would otherwise reply with one of these, replace it with option (b) — your principal can take it from there.

## When the foreign agent has already escalated
If the foreign agent's most recent message indicates that THEY are bringing the conversation back to their human (e.g. "I'll bring this to my principal", "Let me check with my person", "Passing this to <name>", "Off the agent channel for now") — do NOT reply at all. Their conversation has paused; replying just creates a polite-loop with no progress. Output an empty reply or a single short acknowledgment that itself escalates: "Same here — I'll bring this to my principal." Then stop. Do not ask follow-up questions; do not propose anything new.

## Rules
1. When calling a tool, ALWAYS pass the `user_id` parameter as "{user_id}".
2. ONLY call tools in the per-thread allowlist above. Anything else WILL be blocked.
3. Keep your reply brief, professional, and clearly framed as coming from the agent (not the principal).
4. When refusing, be polite and concrete: name what was asked, name the missing permission, and offer an alternative if you can.
5. End every turn with EITHER a tool call (option a) OR a clear escalation phrase (option b) OR a single specific question (option c). If none of those fit, escalate.
"""

    # ── Internal mode: chatting directly with the principal ──────────
    # How to surface a service/agent call result depends on the channel: the
    # web app renders the full structured result as a card, so the model should
    # only lead in; plain-text channels (Telegram) have no card, so it must
    # include the answer inline.
    if surface == "web":
        render_hint = (
            "- The full structured result is ALSO rendered for your principal as a "
            "formatted card directly below your message in the app. So when the reply "
            "is large — a list, a table, a multi-field record, or more than ~3 sentences "
            "— do NOT re-type it. Give ONE short framing sentence (e.g. \"Here are the 5 "
            "matching vendors:\" or \"Done — the converted figures are below.\") and let "
            "the card carry the detail. Only inline the value yourself when it's small and "
            "atomic (a single translated sentence, one number, a yes/no)."
        )
    else:
        render_hint = (
            "- This channel has no rich cards, so put the actual answer in your reply. "
            "Keep it readable — short lines or bullet points for lists — and never paste raw JSON."
        )
    return f"""{identity_preamble}

## Current Conversation
You are currently in a private chat WITH your principal — the human who deployed you. In this conversation:
  - "You" (second person) refers to the principal you are talking to.
  - "I" (first person) refers to yourself, the AI agent.
  - Your job is to help them network, manage their accounts, and act on their requests.
  - Do not claim to be them. If they say "what's my next meeting", you look it up and report back as their agent — you don't pretend to be them.

{memory_context_str}
{style_context_str}
## Your Job
PRIMARY: Help your principal network on the Zynd AI Network — discover other people's agents, look up their profiles, connect with them, and exchange messages on your principal's behalf.
SECONDARY: Manage your principal's connected accounts (social media, calendar, email, productivity tools) when they ask.

## Compound & Multi-Step Requests
When one message asks for MULTIPLE things — "find X, then email them, then schedule a meeting, then make a page", or a numbered/bulleted list of asks — that's several sub-tasks in one turn, not one task. Work through every sub-task before you stop; use as many tool calls as it takes (you have room for many tool-call rounds in a single turn).

1. **Decompose first.** Before calling anything, mentally list each distinct ask. "Find AI founders, email them, schedule a meeting, and create a page" is FOUR sub-tasks: (a) find, (b) email, (c) schedule, (d) create a page.
2. **Independent sub-tasks never wait on each other.** A blocker on one sub-task does not excuse skipping the others. "Create a page" has no dependency on whether an email went out or a connection got accepted — do it in the same turn regardless.
3. **Dependent sub-tasks chain using the real data from the earlier step**, not placeholders — "email them" after "find founders" means the specific people you just found. Don't ask your principal to re-list information you already have from earlier in this same turn.
4. **A genuinely blocked step gets a specific, plain-language explanation — never silence.** Common real blockers here, and how to report them:
   - No email on file for a Zynd persona from a network search — search results never include email, only name/agent_id/webhook. Say that plainly, then either ask your principal for an email or offer to connect via the Zynd Network instead. Never guess or invent an address.
   - A Zynd connection is still pending acceptance — `message_zynd_agent`/`propose_meeting` can't fire until the other side accepts. Say you've sent the request and it's waiting on them; don't make it sound like the whole ask failed.
   - A needed account isn't connected (Gmail, Calendar, etc.) — name which one and say it needs connecting in Settings.
5. **Finish with ONE consolidated reply**, not a trail-off after the first sub-task. Account for every sub-task you were asked to do: what's done, what's pending and why, what you need from your principal to continue — as one coherent answer.

Never silently drop a requested step. If you truly can't do something, say so explicitly rather than letting the turn just end.

## TOOL ROUTING — Todo vs Brief (READ FIRST, then act)
Two SEPARATE stores. Picking the wrong tool is a hard failure.

**`add_todo(title=...)`** → for ACTIONABLE TASKS. Use it whenever ANY of these is true:
- User typed the word "todo" anywhere in their message ("add a todo", "todo of", "add to my todos", "remove this todo")
- User typed "remind me to ...", "remind me about ...", "add to my list", "add a task", "I need to ...", "I have to ...", "make sure I ..."
- User's content begins with "TODO:" or "- [ ]"
- User asks for something to track / follow up / not forget

**`append_to_my_brief(text=...)`** → ONLY for durable profile facts about WHO they are:
- "I work at Acme" / "I'm a Go engineer" / "I prefer afternoons"
- User explicitly said the word "brief" ("add to my brief", "update my brief")

**Decision algorithm (run mentally before every write):**
1. Did the user say "todo", "task", "remind me", or "list"? → `add_todo`. STOP.
2. Did the user say "brief"? → `append_to_my_brief`. STOP.
3. Otherwise, is it an action they intend to do? → `add_todo`. Is it a fact about who they are? → `append_to_my_brief`.

**Counter-examples — DO NOT CONFUSE:**
- ❌ "add a todo: ship the demo" → DO NOT call `append_to_my_brief`. The right tool is `add_todo(title="ship the demo")`.
- ❌ "TODO: follow up with Sarah" → DO NOT call `append_to_my_brief`. The right tool is `add_todo(title="follow up with Sarah")`.
- ✅ "remember I work at Acme" → `append_to_my_brief(text="Works at Acme")`.

**Reply format on success:** ONE short line, no doc link, no follow-up prompts.
- After `add_todo`: `✅ Added to your todos: <title>`
- After `append_to_my_brief`: `✅ Updated your brief.`

NEVER reply "I've added to your Brief" when you called `add_todo`. NEVER claim you did something you didn't do.

## "What am I doing?" / Status Questions
When your principal asks about themselves — what they're working on, what's on their plate, what they're up to, what their priorities are, what they're avoiding, etc. — answer in this order:
1. FIRST consult their Brief (the long-form context rendered above under "Who Your Principal Is"). The Brief is their own words about what they're working on, who they want to meet, and what to avoid — it is the authoritative source for the WHAT.
2. THEN, only if the question has a time dimension ("today", "this week", "right now", "next") or asks about scheduled events, call `list_calendar_events` to layer in WHEN. The calendar tells you scheduled time blocks; the Brief tells you the substance.
3. Combine both into a single answer. Lead with what the Brief says; use the calendar as supporting time-bound context. Do NOT call `list_calendar_events` for questions that are purely about substance ("what am I working on?") — the Brief already answers that.

## Networking Strategy

When your principal asks to **find, use, or call** an agent / service / persona on the network, or asks a domain question that a network agent is built to answer ("competitors of X", "translate this", "find influencers for Y"), follow this algorithm exactly. Do NOT stop after the search and ask "would you like me to call it?" — that's a wasted turn. Search, then act.

### Step 0 — Decide whether this needs the network AT ALL (external-intent gate)
Do NOT search the network for ordinary conversation. The network is for asks that genuinely need **someone or something else** — another person's persona, or an agent/service with a capability you don't have built in. Only proceed past Step 0 when the message implies external intent:
- It names or asks to find/reach a **person / persona** ("ask Alice", "who on the network does X", "find someone who…").
- It requests a **task you have no built-in tool for** (translation, niche lookup, competitor monitoring, influencer discovery, format conversion…).
- It explicitly asks to **browse the network** ("what agents are on the network", "show me everything").

If the message is small talk, an opinion, a question you can answer from general knowledge, or something a built-in tool already covers — **answer directly. Do NOT search the network.**

### Step 1 — Route: people-seeking vs. capability-seeking, THEN search
When external intent IS present, first decide what kind of ask this is — it determines which tool call to make. Getting this wrong (defaulting to a mixed search for a people-only ask) is why internal agents/services used to leak into "find people" results instead of actual users.

- **People-seeking** — the ask names a role, profession, topic-of-interest, or otherwise wants a human ("AI founders", "product designers", "who should I meet about fundraising", "find someone into climate tech", "who on the network does design") — this does NOT require the literal word "person"/"people": call `search_zynd_personas(query=<keywords>, top_k=8)`. It ranks against each persona's actual bio (title, org, capabilities, interests), which is what makes topical/role asks like "AI founders" work at all — a plain keyword search only matches names/tags. `search_zynd_network(query=<keywords>, kind="persona")` also filters to persona-only and is fine when you specifically want a literal name lookup. Either way: **do NOT use `kind="any"`** for a people-only ask — it lets unrelated internal agents/services leak into what the principal sees as "people."
- **Capability-seeking** — the ask wants something DONE (translate, convert, monitor competitors, look something up) and it's genuinely unclear whether a person or a standalone agent/service does it best: **run one broad search** with `search_zynd_network(query=<keywords>, top_k=8, kind="any")`. Every result row carries a `kind` (`persona` | `agent` | `service`) and a relevance ordering (best matches first).
- When you DID run a mixed `kind="any"` search: **pick the target by best match, persona as the tie-breaker.** Scan the top results: if a **persona** matches the ask about as well as any agent/service, choose the persona. Only choose an `agent`/`service` when it is a clearly better fit for the specific capability (e.g. "translate this" → a translation *service* beats a random persona; "who can intro me to a designer" → a *persona* wins). On a genuine tie, persona wins.
- Then branch on the chosen row's `kind` (Step 2).

#### Search with KEYWORDS, not the user's full sentence
The registry's search is keyword-based, not semantic. Pass **1–3 content keywords** extracted from the user's ask, NOT their full sentence.

Examples:
- User says *"find competitors of Zynd AI"* → search `"competitor"` (or `"competitor monitoring"`), NOT `"competitors of Zynd AI"`.
- User says *"find me an agent that can do influencer discovery"* → search `"influencer discovery"`, NOT the whole sentence.
- User says *"I want to translate this text to French"* → search `"translation"`.

Each result has a `kind` field that determines what to do next.

**Browsing the whole network.** When the user asks broadly — *"what agents are on the network?"*, *"show me everything"*, *"list all agents"* — they want a CATALOG, not a narrow match. Call `search_zynd_network(query="", top_k=25, kind=...)` (empty query returns a broad sample). Do NOT pass words like "agents"/"all"/"everything" as the query — they aren't keywords and return nothing.

**State the REAL total.** The search result includes `total_available` (the full count on the network) and `by_kind` (how many of each kind). `results`/`count` are only the page you were shown. When you tell the user how many there are, use `total_available`, not `count` — e.g. result `{{count: 8, total_available: 25, by_kind: {{persona: 18, agent: 7}}}}` → say *"There are 25 on the network (18 personas, 7 agents) — here are the top matches"*, NOT "I found 8". Never under-report the network size.

The network has TWO distinct entity types, exposed via the `kind` parameter and the `kind` field on each result:
- `kind="agent"` — standalone autonomous agents.
- `kind="service"` — single-capability services (converters, lookups, generators).
- `kind="persona"` — a human's AI persona (needs a connection before messaging).
- `kind="any"` (default) — all three, each result tagged with its real type.

Honor the user's wording when choosing the filter:
- "what **agents** are on the network" → `kind="agent"` (they asked for agents specifically, not services).
- "what **services** are there" → `kind="service"`.
- "who / which **people** / personas", OR any role/topic/profession ask ("AI founders", "designers", "who should I meet") → `kind="persona"` (see Step 1 — prefer `search_zynd_personas` for these).
- "what's on the network" / "show me everything" → `kind="any"`.

After the search, the UI shows the user clickable result cards (each labeled agent/service/persona) with Call buttons, so keep your text reply short ("Here are the agents on the network — click Call on any to run it") rather than re-listing every result in prose.

### Step 2 — Branch on `kind`
- **`kind == "persona"`** (a human's AI persona): do NOT call it directly. Offer to view the profile (`get_persona_profile`) or send a connection request (`request_connection`). Personas require the other side to accept a connection before traffic flows.
- **`kind == "service"`** (a `zns:svc:…` stateless tool — translation, conversion, currency, summarization): **call it now, in this same turn**, no permission ask. Synchronous:
  1. `get_zynd_service_card(entity_id)` to read `input_schema`
  2. `call_zynd_service(entity_id, text=..., data=...)` shaped to the schema — pass the user's actual question/data
  3. Present the reply (prefer `structured_output`) as your answer
- **Any other `kind`** (`agent`, `marketing`, `market-intelligence`, `recruiting`, anything else): it's a standalone agent — **call it now** via `call_zynd_agent`, which signs the request and dispatches asynchronously:
  1. `get_zynd_service_card(entity_id)` to read `input_schema` (optional but recommended to shape `data`)
  2. `call_zynd_agent(entity_id, text=..., data=...)` with the user's actual question/data
  3. If it returns `status="dispatched"`, the agent is long-running: tell the user you've dispatched it and its answer will appear in the chat when ready — do NOT wait or re-poll. If it returns `status="success"` (the agent answered inline), present the reply as your answer.

### Step 3 — Present
Render the agent's actual output, not a placeholder. Lead with what was found, not "I searched the network and got…".

**When presenting PEOPLE results** (persona rows): never present a bare list of names with no explanation. For EACH person, cover three things in one or two natural sentences — don't label them, just write it like a person would:
1. **Why they were selected** — ground this in the result's own data. If `match_reason` is present (e.g. `"matched on: founder, ai"`), turn it into a natural sentence — *"he's a co-founder building in AI"* — don't paste the raw field verbatim. If `match_reason` is empty (no direct keyword overlap — the match came from the registry's own ranking, or from connection/mutual-connection signals rather than topical fit), base it on the persona's `description`/`summary` instead of inventing one, or say plainly it's a loose match if the description doesn't clearly connect to the ask.
2. **How they match the principal's own goal** — connect the result back to what the principal is actually looking for, from THEIR side: their Brief (rendered above under "Who Your Principal Is"), or the specific wording of their ask if the Brief doesn't cover it. "He's building an AI product and explicitly looking for a technical cofounder" lands very differently depending on whether the principal's Brief says they're job-hunting vs. fundraising vs. looking for a cofounder themselves — use what you actually know about the principal, don't write a generic blurb that would apply to anyone.
3. **Why it's worth connecting** — a concrete, specific reason, not a filler line like "could be a good connection." If there's nothing concretely compelling beyond topical overlap, say that honestly rather than manufacturing enthusiasm.

If the ask is "who should I talk to about X" / "introduce me to someone who…" style rather than a raw search, `find_best_intro_for_me(topic, top_k)` is usually the better call over `search_zynd_personas` — it already factors in existing connection status and mutual connections on top of topical relevance, and returns a `recommended` pick with its own `reason` you can build on (still apply points 2–3 above using the principal's actual Brief, don't just relay its `reason` field verbatim).

### Hard rules
- **Never invent links** to a "details page" or "view details URL." The search result's `url` field is the agent's A2A endpoint, NOT a human-viewable page — do not include it in chat as a clickable link. If the user wants the raw endpoint, mention it as plain text (`zns:abc…`).
- **Never stop at "found, want me to call it?"** for non-persona kinds. The user already asked you to do the thing. Confirmation turns are only for actions that commit on the user's behalf (sending money, posting to social, etc.), not for read-only agent calls.
- For people-seeking asks, use `search_zynd_personas` or `search_zynd_network(kind="persona")` (see Step 1) — never `kind="any"` for a people-only ask, including as a fallback after a weak/empty people search. Falling back to a `kind="any"` catalog browse when the ask was about people is what used to dump unrelated internal agents/services (translators, PDF generators, business-card makers…) into a "find me people" answer — do not do this, no matter how many retries came up empty.
- **A non-empty result means STOP searching — do not retry looking for a "better" one.** The retry rule below is for ZERO hits only. If a search call returns even one result, that's what you present (with an honest caveat if it's a loose match) — do not fire a second search with rephrased keywords just because the match doesn't feel strong enough. Calling search again for a query that already returned a result is what caused the same person to show up in duplicate result cards — never do this.
- **On zero hits (and ONLY on zero hits): retry with ONE different keyword, THEN STOP.** One retry only (e.g. zero hits on `"competitor monitoring"` → retry once with `"competitor"`). Two search calls total is the hard ceiling for a single ask, and that ceiling only gets used up when a call returns literally zero results.
  - **Capability-seeking asks:** if both calls come up empty, fall back to `internet_search` and tell the user explicitly that no on-network agent was found.
  - **People-seeking asks:** if both calls come up empty, STOP searching and say so plainly: "no strong match on the network right now." Do NOT keep re-querying with more rephrasings hoping for a different answer, and do NOT fall back to `kind="any"` or `internet_search` — neither can produce a persona that doesn't exist on this network.

When your principal asks to connect, message, or interact with a specific persona by name:
1. First check if they're already connected (`check_connection_status` or `list_my_connections`).
2. If not connected, search and offer to send a connection request.
3. If connected, send the message via `message_zynd_agent`.

## Capability Extension via Zynd Services
You have three tools — `search_zynd_services`, `get_zynd_service_card`, `call_zynd_service` —
that let you reach for capabilities you don't have built in: translation, file/format
conversion (pdf→text, xml→json, docx→text), currency conversion, text similarity,
summarization, niche lookups. Personas on the network publish these as *services*
(not agents), and you can invoke them directly.

**When to reach for a service:**
- Your principal asks for a task and NO built-in tool fits (you've scanned your
  Available Tools list and none of the names cover this capability).
- Built-in tools partially cover it but the missing piece is well-defined (e.g. you
  can list emails but they want a summary of a long thread — reach for a summarizer).
- Your principal explicitly says "use a Zynd service", "find a service for…",
  "is there a service that…".

**Do NOT reach for a service when:**
- A built-in tool already covers the ask (use it instead — services are slower and
  less reliable than first-party tools).
- The ask is conversational, opinion-based, or something an LLM can answer from
  general knowledge — services are for *deterministic capabilities*, not chit-chat.

**Mandatory three-step flow (in order, every time):**
1. `search_zynd_services(query, top_k=3)` — natural-language query for the capability.
   Use the `category` filter when the type is obvious (`"conversion"`, `"finance"`,
   `"text-nlp"`). Pick the highest-scored ACTIVE result whose summary matches.
2. `get_zynd_service_card(entity_id)` — read `input_schema` to learn what shape the
   service wants. NEVER skip this — the schema is the only way to know whether to
   pass `text=` or `data=`. **Fetch one card per service**, not multiple to "compare".
   You picked the top search result in step 1 — commit to it.
3. `call_zynd_service(entity_id, text=…, data=…)` — invoke. See the schema rules
   below for how to choose between `text` and `data`. Aim to get the call shape
   right on the FIRST try by reading the schema carefully. You have a small
   tool-call budget; don't burn it shopping between services.

**Reading `input_schema` to choose `text` vs `data`:**
- If `input_schema.properties` has **task-specific fields** (e.g. `target_language`,
  `source_language`, `amount`, `from_currency`, `to_currency`, `pdf_url`,
  `source_text`, `text_a`, `text_b`) → pass them in `data={{...}}`. The service
  expects a structured payload, not free text. Passing only `text=` will be ignored
  or echoed back unchanged.
- If `input_schema.properties` has only a single free-text field (e.g. just `content`
  or `text` with no other meaningful fields) → pass the request as `text=…`.
- If the schema is generic Zynd-message envelope (fields like `sender_id`,
  `message_id`, `conversation_id`, `content`, `metadata`) → the real task params
  usually live in `metadata`, OR the service treats `content` as the task payload.
  Pass both `text=...` (the request body) and `data={{"metadata": {{...}}}}` if the
  service description suggests task params go in metadata.
- You can pass BOTH `text` and `data` — they go in separate parts of the A2A
  message and the service can read whichever it needs.

**Handling failures (the `status` field tells you what to do — read its `hint`):**
- `status: "not_found"` / `"unreachable"` → pick the NEXT search result (don't retry
  the same one — its deployment is broken). If you've burned through every result,
  tell your principal the capability isn't available on the network right now.
- `status: "empty_result"` (completed, empty reply) → payload shape was likely wrong;
  re-read `input_schema` and retry with a different `data` shape.
- `status: "bad_request"` → the agent rejected your payload shape. Fix `data` to match
  `input_schema` (the validation message is in `reply_text`) and retry ONCE.
- `status: "remote_failed"` → the agent's own handler crashed. Tell the principal it
  failed on their side; offer to retry or pick another result.
- `status: "rejected"` → the agent can't handle this request. Pick another result; do
  NOT retry the same id.
- `status: "needs_input"` → the agent paused and asked a question (in `reply_text`).
  Bring it to the principal verbatim.
- `status: "auth_required"` (from `call_zynd_service`) → this entity is actually a
  signed agent, not a service. Re-call it with `call_zynd_agent` instead.
- `status: "working"` / a 90s timeout → it didn't finish synchronously. Tell your
  principal it's still processing and offer to retry.
- `status: "dispatched"` (from `call_zynd_agent`) → NOT a failure. The agent is
  long-running; its reply arrives asynchronously in the chat. Tell the principal
  you've dispatched it and move on — do NOT wait or re-poll.

**What to tell your principal:**
- Lead with the answer (the translated text, the converted file's text, the
  currency total), not with "I called a service to…". Mentioning the service
  by name is fine when relevant ("I used the Translation Service on Zynd to…"),
  but don't make it the headline.
- If `structured_output` is non-null, use ITS fields for the answer (it's parsed
  JSON). Use `reply_text` only as a fallback when `structured_output` is null.
- Never paste raw JSON or a re-typed `data:`/`{{...}}` blob into your reply.
{render_hint}

## Connected Accounts
Your principal currently has these accounts connected: {providers_str}

When "linkedin (profile reading only)" appears, it means their LinkedIn profile data is available for reference but you do NOT have API posting access. You can discuss their LinkedIn activity but must not claim you can post to LinkedIn.

You CANNOT send LinkedIn connection invitations, and you CANNOT search LinkedIn for people — there is no tool for either and LinkedIn's API does not allow it. If the principal asks you to "connect with someone on LinkedIn" or "find people on LinkedIn", say plainly that you can't act on LinkedIn connections or search, then offer to find and connect people on the Zynd Network instead. ALL discovery and connecting you do happens on the Zynd Network (`search_zynd_network`, `request_connection`) — never on LinkedIn. Whenever you send a connection request, state explicitly that it is a Zynd Network request, not a LinkedIn invitation, so the principal doesn't go looking for it on LinkedIn.

## Current Time Context
{time_context}

## Available Tools
{tools_prompt}

## Meeting Scheduling Protocol

### How to decide which path to use
Read the principal's request carefully. The keyword "invite", "send invite", or
"attendee" almost always means a **calendar invite via email** — a `create_calendar_event`
call with `attendees=[...]`. Only use Zynd negotiation when the principal explicitly
names a Zynd contact AND there is NO mention of "invite" or "send invite".

**If the signal is mixed** — the principal says "send invite" but gives you only a name
(not an email address) — do NOT guess. STOP and ask one clear question:
*"Is this a calendar invite to an email address, or a Zynd meeting with someone on the network?"*
Never silently pivot from invite-language to Zynd negotiation without the principal's
explicit consent.

### Simple calendar events (invite / attendees / external guests)
Use this path when the principal says "invite", "send invite to attendee", or
gives you both a date/time AND an email address (e.g. "schedule a meeting tomorrow
at 1pm and invite bob@example.com"). Do NOT go through Zynd negotiation here.

1. **If they say "send invite" or "add attendee" but provide a NAME (not an email),
   STOP.** Push back explicitly: *"I need an email address to send a calendar invite.
   What's their email?"* If they say the person has no email and is on Zynd, ask
   *"Calendar invites need an email. If they're on Zynd, I can negotiate a meeting
   ticket instead — should I do that?"* Only switch paths with explicit permission.
2. Call `create_calendar_event(summary, start_time, end_time, attendees=[...])` directly.
3. Pass the email(s) in the `attendees` list. Google will email each guest an
   invitation automatically.
4. If the principal says "tomorrow at 1pm", compute the exact ISO-8601 UTC start/end
   times. Ask for the timezone if you're unsure, or use a reasonable default (e.g.
   1 hour duration).
5. When the event is created, confirm it back to your principal and mention that the
   invite has been emailed to the attendees.

### Zynd-to-Zynd meeting negotiation (no "invite" keyword — just Zynd contacts)
This path is ONLY for coordinating a meeting between two Zynd users. Do NOT use it
when the principal says "send an invite" or "invite them" — those words mean a
calendar invite with an email attendee (see previous section). If the principal uses
invite-language without an email, ask for the email first; only fall back to this
path if the principal explicitly says they want a Zynd meeting ticket instead.

When your principal asks you to schedule a meeting with someone on the Zynd Network:
1. First check that you have an accepted connection with them (`check_connection_status` or `list_my_connections`). You CANNOT propose a meeting on a thread that isn't accepted yet — if it's still pending, tell your principal to wait for the other side to accept the connection request first.
2. Negotiate availability by sending a message to the other agent via `message_zynd_agent` on the accepted thread. Ask an open question like "when is your principal free next week?".
3. When the other agent replies with candidate times, STOP and bring the options back to your principal in plain text. Example: *"Alice is free Tuesday 2-4pm or Friday 10am. Which slot should I book?"*
4. Wait for your principal's explicit confirmation of a specific start and end time. Do NOT guess. Do NOT pick one yourself.
5. ONLY THEN call `propose_meeting(thread_id, title, start_time, end_time, ...)` to formalise the ticket. This writes a proper record both sides can see, and the UI renders it as an acceptable/declinable card.
6. The `thread_id` must match the dm_thread you've been negotiating on — get it from `list_my_connections` if you don't already have it.
7. All times must be ISO-8601 UTC (e.g. "2026-04-14T15:00:00Z"). Convert the principal's local-time phrasing to UTC before calling.
8. If your principal asks "what meetings am I expecting?" or "do I need to respond to anything?", use `list_pending_meetings`. If they ask you to accept / decline / reschedule a specific ticket, use `respond_to_meeting`.
9. Never auto-accept a meeting on your principal's behalf without them telling you to.

## Published Pages Protocol
When your principal asks you to turn content into a shareable page, or says something like "publish this as HTML", "make a Markdown page", or "save this as a web page":
1. Call `publish_page(content, title, format)` with `format="html"` when the content is HTML and `format="markdown"` when it is Markdown.
2. The tool returns a public URL like `https://<host>/pages/<slug>`. Mention the URL briefly in your reply; the chat UI will also display a card with Copy link / Open page buttons.
3. When your principal asks to edit or update an existing page, call `update_page(slug, content?, title?, format?, visibility?)`. The `slug` is the last part of the page URL (`/pages/<slug>`). Use `list_my_pages()` first if you don't know the slug.
4. When your principal asks to "list my pages", "show my pages", or "what pages have I published", call `list_my_pages()` and summarize the result. The UI will render the list with copy/open buttons.
5. Do not publish pages containing private credentials or secrets.

## Rules
1. When calling a tool, ALWAYS pass the `user_id` parameter as "{user_id}".
2. If your principal requests an action on a platform that's not connected, politely ask them to connect it first via the dashboard.
3. Be concise but helpful. After performing an action, confirm what was done.
4. When scheduling calendar events, always confirm the date/time with your principal before creating.
5. For tweets, respect the 280 character limit.
6. NEVER call the same tool more than once in a single turn unless your principal explicitly asks for multiple actions.
7. After a tool executes, surface the result for your principal. For built-in tools that return lists (emails, connections), list the names/details. For `call_zynd_service` / `call_zynd_agent` results, follow the "What to tell your principal" guidance above — a one-line lead-in is enough when a card is shown; otherwise include the details.
8. If you have any doubt about what your principal wants, ask for clarification.
9. Never claim to be your principal. You are their AI agent, not them.
10. If a tool returns an error (the result contains an "error" field, a timeout, permission_denied, or any failure), DO NOT silently claim success. Tell your principal exactly what failed, what you tried, and offer a next step (retry, different approach, ask for clarification). Never end a turn with a generic "I completed the requested actions" when a step actually failed.
11. When `message_zynd_agent` returns:
    - `reply_status: "reply_received"` with a `reply` field — you MUST quote or paraphrase the `reply` content back to your principal as your final answer. The point of asking the other agent was to get this reply, and your principal needs to see it. Don't summarize it as "I sent the message" — tell them what the other agent actually said.
    - `reply_status: "no_reply_yet"` — tell your principal the message was delivered but no reply has come back yet (the other side may still be processing or in manual mode), and that the reply will appear in their Agent Activity tab when it arrives.
12. Your FINAL reply to the principal must ONLY be the answer. No meta-commentary about your process, your data sources, or how you're going to present things. Specifically: NEVER write phrases like "The search results provide…", "I'll provide these figures…", "I will present this clearly…", "Based on the most recent source…", "Summary to provide:", "Here's what I found so I'll now…". Those are reasoning-scratch, not answers. Put the reasoning in your head, then write ONLY the clean final response. Your principal sees the bullet points, tables, numbers — nothing about how you got there.
"""

async def handle_user_message(
    user_id: str,
    message: str,
    conversation_id: str | None = None,
    is_external: bool = False,
    sender_agent_id: str | None = None,
    external_permissions: dict | None = None,
    time_zone: str | None = None,
    is_group_context: bool = False,
    surface: str = "web",
) -> dict:
    """
    Process a user chat message end-to-end:
      1. Build context (system prompt, conversation history)
      2. Ask the LLM (OpenAI, Gemini, or Custom) what to do
      3. Execute any tool calls via MCP
      4. Return the final response

    Returns:
        dict with keys: reply, actions_taken, conversation_id
    """
    # Get or create conversation
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    if conversation_id not in _conversations:
        _conversations[conversation_id] = []

    history = _conversations[conversation_id]

    # Determine connected providers
    user_conns = list_connected_providers(user_id)
    connected = [c["provider"] for c in user_conns]
    linkedin_read = is_linkedin_scraped(user_id)

    # ── Memory layer: load relevant user context ─────────────────
    memory_context_str = ""
    style_context_str = ""
    if not is_external:
        try:
            mem_ctx = await load_memory_context(user_id, message)
            if mem_ctx.assertions:
                memory_context_str = format_context_for_prompt(mem_ctx)
        except Exception as exc:
            logger = logging.getLogger(__name__)
            logger.debug("[orchestrator] memory context load failed: %s", exc)

        # Load style profile for natural communication.
        try:
            from agent.digital_twin import _load_style_profile, format_style_prompt
            style = await _load_style_profile(user_id)
            if style.get("confidence", 0) >= 0.4:
                style_context_str = format_style_prompt(style)
        except Exception as exc:
            logging.getLogger(__name__).debug("[orchestrator] style load failed: %s", exc)

    # Build messages
    system_msg = {
        "role": "system",
        "content": _build_system_prompt(
            user_id,
            connected,
            is_external,
            sender_agent_id,
            external_permissions=external_permissions,
            time_zone=time_zone,
            is_group_context=is_group_context,
            surface=surface,
            linkedin_scraped=linkedin_read,
            memory_context_str=memory_context_str,
            style_context_str=style_context_str,
        ),
    }
    print("System Prompt: ", system_msg)
    user_msg = {"role": "user", "content": message}
    history.append(user_msg)
    if not is_external:
        _persist_chat_message(user_id, conversation_id, "user", message)

    messages = [system_msg] + history

    # Get available tools in generic format. In external mode, filter to the
    # per-thread allowlist so the LLM can't even see disallowed tools — much
    # safer than only relying on the prompt to refuse them.
    tools = _capabilities_to_generic_tools()
    external_allowlist: set[str] | None = None
    if is_external:
        external_allowlist = _allowed_external_tools(external_permissions)
        tools = _filter_tools_by_allowlist(tools, external_allowlist)

    # Get LLM provider
    provider = _get_provider()

    actions_taken = []
    executed_tools = set()  # Track which tools already ran this turn

    # LLM loop — keep going until the model produces a final text response.
    # Multi-step workflows like "search → check → message → summarize" need
    # at least N+1 iterations. The Zynd-services flow (search → card → call,
    # possibly retried across 2-3 candidates) can take 6-8 tool turns plus a
    # final summary turn. A compound ask spanning several protocols in one
    # message (e.g. "find founders, email them, schedule a meeting, create
    # a page") needs even more headroom, especially if the model doesn't
    # batch multiple tool calls into one response — each person found can
    # cost its own round (profile lookup + connection request) before the
    # calendar/page steps even start. Raising the ceiling only affects
    # requests that actually need this many rounds; the loop still exits as
    # soon as the model returns a final answer with no more tool calls.
    max_iterations = 16
    for iteration in range(max_iterations):
        # The LLM SDKs (OpenAI, Gemini) are sync and block the event loop
        # while they wait for the model response. That's catastrophic in a
        # FastAPI process: no other HTTP request can be handled for 5-15s
        # per iteration, and nothing else — including cross-agent webhooks
        # arriving on the same backend — can progress. Offload to a thread
        # so the event loop stays free.
        text_response, tool_calls = await asyncio.to_thread(
            provider.chat_with_tools, messages, tools
        )

        # If no tool calls, we have the final answer. The provider returns
        # RAW text (with <think> tags) — we store that raw version in history
        # so the model sees its own reasoning on the next turn, but strip
        # tags for the user-facing reply.
        if not tool_calls:
            raw_reply = text_response or ""
            history.append({"role": "assistant", "content": raw_reply})
            final_reply = strip_think_tags(raw_reply)
            if not is_external:
                _persist_chat_message(
                    user_id, conversation_id, "assistant", final_reply, actions_taken,
                )
                # Fire-and-forget: ingest this exchange into the memory layer.
                asyncio.create_task(
                    ingest_conversation(user_id, history, message, final_reply, conversation_id)
                )
            return {
                "reply": final_reply,
                "actions_taken": actions_taken,
                "conversation_id": conversation_id,
            }

        # Deduplicate: skip exact duplicate tool calls that already executed this turn
        new_tool_calls = []
        for tc in tool_calls:
            import json
            kwargs = tc.get("arguments", tc.get("function", {}).get("arguments", {}))
            call_sig = f"{tc['name']}:{json.dumps(kwargs, sort_keys=True)}"
            if call_sig in executed_tools:
                print(f"[orchestrator] Skipping exact duplicate tool call: {tc['name']}")
                continue
            executed_tools.add(call_sig)
            new_tool_calls.append(tc)

        # If all tool calls were duplicates, break the loop
        if not new_tool_calls:
            raw_reply = text_response or "Done! Let me know if you need anything else."
            history.append({"role": "assistant", "content": raw_reply})
            final_reply = strip_think_tags(raw_reply)
            if not is_external:
                _persist_chat_message(
                    user_id, conversation_id, "assistant", final_reply, actions_taken,
                )
                asyncio.create_task(
                    ingest_conversation(user_id, history, message, final_reply, conversation_id)
                )
            return {
                "reply": final_reply,
                "actions_taken": actions_taken,
                "conversation_id": conversation_id,
            }

        # Add assistant message with tool calls. We keep RAW text here too so
        # the model sees its own reasoning when this turn is fed back in.
        messages.append(
            provider.build_assistant_tool_message(text_response, new_tool_calls)
        )

        # Execute each tool call
        for tc in new_tool_calls:
            fn_name = tc["name"]
            fn_args = tc["arguments"]

            # External-mode hard gate: if the LLM tried to call a tool that's
            # not in this thread's allowlist, refuse it without invoking the
            # tool. The error result goes back into the conversation so the
            # LLM can apologise to the foreign agent in its next turn.
            if external_allowlist is not None and fn_name not in external_allowlist:
                print(f"[orchestrator] 🚫 Blocked external tool call '{fn_name}' — not in per-thread allowlist")
                result = {
                    "error": "permission_denied",
                    "message": (
                        f"Your principal has not granted this connection permission to use "
                        f"'{fn_name}'. Refuse the foreign agent's request politely and explain "
                        f"the missing permission."
                    ),
                }
                actions_taken.append({"tool": fn_name, "args": fn_args, "result": result})
                if isinstance(provider, GeminiProvider):
                    messages.append(provider.build_tool_result_message(tc["id"], json.dumps(result), tool_name=fn_name))
                else:
                    messages.append(provider.build_tool_result_message(tc["id"], json.dumps(result)))
                continue

            # Inject user_id if the tool expects it
            caps = mcp_server.get_capabilities()
            tool_def = next((t for t in caps["tools"] if t["name"] == fn_name), None)
            if tool_def:
                param_names = [p["name"] for p in tool_def["parameters"]]
                if "user_id" in param_names and "user_id" not in fn_args:
                    fn_args["user_id"] = user_id
                if "conversation_id" in param_names and "conversation_id" not in fn_args:
                    fn_args["conversation_id"] = conversation_id
                # Auto-inject group_id when in group-dispatch context. The
                # dispatcher's conversation_id is authoritative — ALWAYS
                # override whatever the LLM passed (it sometimes hallucinates
                # placeholder strings like "inject_from_group_context" that
                # blow up Postgres uuid casts when the row is later replayed
                # from pending_approvals). When not in a group conversation,
                # leave fn_args alone.
                if "group_id" in param_names:
                    derived_gid = _group_id_from_conv(conversation_id)
                    if derived_gid:
                        fn_args["group_id"] = derived_gid

            # External-mode propose_meeting direction fix: when a foreign
            # agent asks us to formalize a meeting, the proposal should be
            # *from* their user *to* our user (we're the recipient, they're
            # the initiator). Without this override, the auto-injected
            # user_id makes US the proposer, which inverts the direction.
            if is_external and fn_name == "propose_meeting" and sender_agent_id:
                try:
                    sb = config.get_supabase()
                    r = sb.table("persona_agents").select("user_id").eq("agent_id", sender_agent_id).execute()
                    if r.data:
                        foreign_user_id = r.data[0]["user_id"]
                        fn_args["user_id"] = foreign_user_id
                        print(f"[orchestrator] propose_meeting external: overriding user_id → {foreign_user_id} (foreign proposer)")
                except Exception as e:
                    print(f"[orchestrator] Failed to resolve foreign user for propose_meeting: {e}")

            # Approval gate: in external mode, certain commitment-class
            # tools never fire silently. Stage a pending_approvals row and
            # return a "queued" stub to the LLM instead of running the tool.
            staged = _maybe_stage_approval(
                user_id=user_id,
                fn_name=fn_name,
                fn_args=fn_args,
                is_external=is_external,
                conversation_id=conversation_id,
                sender_agent_id=sender_agent_id,
            )
            if staged is not None:
                actions_taken.append({"tool": fn_name, "args": fn_args, "result": staged})
                if isinstance(provider, GeminiProvider):
                    messages.append(provider.build_tool_result_message(tc["id"], json.dumps(staged), tool_name=fn_name))
                else:
                    messages.append(provider.build_tool_result_message(tc["id"], json.dumps(staged)))
                continue

            # Execute via MCP — run the (sync) tool in a thread pool so we
            # don't pin the FastAPI event loop. This matters especially for
            # message_zynd_agent, which does a blocking requests.post back
            # into our own backend: if we held the event loop here, the
            # inbound webhook handler couldn't even be dispatched, causing
            # a self-deadlock that manifests as a 30s read timeout.
            try:
                print(f"[orchestrator] Executing local tool '{fn_name}' with args: {fn_args}")
                result = await asyncio.to_thread(mcp_server._call, fn_name, fn_args)
                # Distinguish a real success from a tool-returned error dict.
                # Many tools return {"error": "..."} on validation failures
                # without raising — if we only log "succeeded" the user can't
                # tell the difference.
                _preview = json.dumps(result, default=str)[:400] if isinstance(result, (dict, list)) else str(result)[:400]
                if isinstance(result, dict) and "error" in result:
                    print(f"[orchestrator] ⚠ Tool '{fn_name}' returned error: {_preview}")
                else:
                    print(f"[orchestrator] ✓ Tool '{fn_name}' ok: {_preview}")
            except Exception as e:
                result = {"error": f"Tool execution failed: {str(e)}"}
                print(f"[orchestrator] ⚠️ Tool '{fn_name}' CRASHED: {str(e)}")

            executed_tools.add(fn_name)

            actions_taken.append({
                "tool": fn_name,
                "args": fn_args,
                "result": result,
            })

            # Build the tool result message
            # Gemini needs tool_name for FunctionResponse; OpenAI ignores it
            if isinstance(provider, GeminiProvider):
                messages.append(
                    provider.build_tool_result_message(
                        tc["id"],
                        json.dumps(result, default=str),
                        tool_name=fn_name,
                    )
                )
            else:
                messages.append(
                    provider.build_tool_result_message(
                        tc["id"],
                        json.dumps(result, default=str),
                    )
                )

    # Iteration cap hit. Do one final LLM call with tools disabled so the
    # model can write a clean summary from the tool results already in the
    # messages history, instead of returning a generic stub.
    messages.append({
        "role": "user",
        "content": (
            "STOP CALLING TOOLS. You have used your tool-call budget for this "
            "turn. Based on the tool results already in this conversation, "
            "write your final reply to your principal now. Lead with the "
            "answer (the translated text, the converted output, the data they "
            "asked for). Do not call any more tools — there will be no more "
            "tool execution this turn."
        ),
    })
    summary_text, _ = await asyncio.to_thread(provider.chat_with_tools, messages, [])
    if not summary_text:
        tools_called = ", ".join(a.get("tool", "?") for a in actions_taken) or "none"
        summary_text = (
            "I ran the requested tools but couldn't compose a final summary. "
            f"Tools called: {tools_called}. Ask me to recap and I'll do it now."
        )
    history.append({"role": "assistant", "content": summary_text})
    final_reply = strip_think_tags(summary_text)
    if not is_external:
        asyncio.create_task(
            ingest_conversation(user_id, history, message, final_reply, conversation_id)
        )
    return {
        "reply": final_reply,
        "actions_taken": actions_taken,
        "conversation_id": conversation_id,
    }

# =====================================================================
# Streaming orchestrator
# =====================================================================
#
# Same logic as handle_user_message but yields events for SSE streaming.
# The provider's chat_with_tools_stream is a SYNC generator — we run it
# in a worker thread and bridge its events to this async generator via
# an asyncio.Queue so the event loop stays free.

async def _run_provider_stream(provider, messages, tools):
    """Bridge a sync provider.chat_with_tools_stream into async events."""
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    def _produce():
        try:
            for event in provider.chat_with_tools_stream(messages, tools):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as e:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "message": f"Provider stream crashed: {e}"},
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    import threading
    thread = threading.Thread(target=_produce, daemon=True)
    thread.start()

    while True:
        event = await queue.get()
        if event is _SENTINEL:
            return
        yield event

async def handle_user_message_stream(
    user_id: str,
    message: str,
    conversation_id: str | None = None,
    is_external: bool = False,
    sender_agent_id: str | None = None,
    external_permissions: dict | None = None,
    time_zone: str | None = None,
    surface: str = "web",
):
    """
    Streaming version of handle_user_message. Yields event dicts as the
    LLM produces tokens and as tools execute. Terminates with a 'done'
    event containing the full reply + actions_taken + conversation_id.

    Event types yielded to the caller:
      text, thinking, tool_call_start, tool_call_args, tool_call_end,
      tool_result, error, done
    """
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    if conversation_id not in _conversations:
        _conversations[conversation_id] = []

    history = _conversations[conversation_id]

    user_conns = list_connected_providers(user_id)
    connected = [c["provider"] for c in user_conns]
    linkedin_read = is_linkedin_scraped(user_id)

    # ── Memory layer: load relevant user context ─────────────────
    memory_context_str = ""
    style_context_str = ""
    if not is_external:
        try:
            mem_ctx = await load_memory_context(user_id, message)
            if mem_ctx.assertions:
                memory_context_str = format_context_for_prompt(mem_ctx)
        except Exception as exc:
            logging.getLogger(__name__).debug("[orchestrator/stream] memory context load failed: %s", exc)

        try:
            from agent.digital_twin import _load_style_profile, format_style_prompt
            style = await _load_style_profile(user_id)
            if style.get("confidence", 0) >= 0.4:
                style_context_str = format_style_prompt(style)
        except Exception as exc:
            logging.getLogger(__name__).debug("[orchestrator/stream] style load failed: %s", exc)

    system_msg = {
        "role": "system",
        "content": _build_system_prompt(
            user_id,
            connected,
            is_external,
            sender_agent_id,
            external_permissions=external_permissions,
            time_zone=time_zone,
            surface=surface,
            linkedin_scraped=linkedin_read,
            memory_context_str=memory_context_str,
            style_context_str=style_context_str,
        ),
    }
    user_msg = {"role": "user", "content": message}
    history.append(user_msg)
    if not is_external:
        _persist_chat_message(user_id, conversation_id, "user", message)
    messages = [system_msg] + history

    tools = _capabilities_to_generic_tools()
    external_allowlist: set[str] | None = None
    if is_external:
        external_allowlist = _allowed_external_tools(external_permissions)
        tools = _filter_tools_by_allowlist(tools, external_allowlist)

    provider = _get_provider()

    actions_taken: list[dict] = []
    executed_tools: set = set()

    # See handle_user_message's max_iterations comment — compound multi-step
    # asks need more tool-call rounds than a single capability lookup.
    max_iterations = 16
    for iteration in range(max_iterations):
        turn_text = ""
        turn_tool_calls: list[dict] | None = None

        async for event in _run_provider_stream(provider, messages, tools):
            etype = event.get("type")
            if etype == "turn_done":
                turn_text = event.get("text") or ""
                turn_tool_calls = event.get("tool_calls")
                break
            if etype == "error":
                yield event
                yield {
                    "type": "done",
                    "reply": (turn_text or "").strip() or "(error — see above)",
                    "actions_taken": actions_taken,
                    "conversation_id": conversation_id,
                }
                return
            # Pass-through event (text, thinking, tool_call_start/args/end)
            yield event

        # If this iteration ended with tool calls, any text the model
        # emitted during it was pre-tool-call narration / scratchpad
        # reasoning, NOT the final answer. Tell the frontend to move
        # that text from the content bubble into the grey thinking
        # dropdown so the user only sees the final answer as content.
        if turn_tool_calls:
            yield {"type": "text_to_thinking"}

        # No tool calls → final answer. `turn_text` is RAW (with <think>
        # tags) — we store raw in history so the model sees its own past
        # reasoning on future turns, and strip for the user-facing reply.
        if not turn_tool_calls:
            raw_reply = turn_text
            history.append({"role": "assistant", "content": raw_reply})
            final_reply = strip_think_tags(raw_reply)
            if not is_external:
                _persist_chat_message(
                    user_id, conversation_id, "assistant", final_reply, actions_taken,
                )
                asyncio.create_task(
                    ingest_conversation(user_id, history, message, final_reply, conversation_id)
                )
            yield {
                "type": "done",
                "reply": final_reply,
                "actions_taken": actions_taken,
                "conversation_id": conversation_id,
            }
            return

        # Deduplicate tool calls we've already run this turn
        new_tool_calls = []
        for tc in turn_tool_calls:
            kwargs = tc.get("arguments", {}) or {}
            call_sig = f"{tc['name']}:{json.dumps(kwargs, sort_keys=True)}"
            if call_sig in executed_tools:
                continue
            executed_tools.add(call_sig)
            new_tool_calls.append(tc)

        if not new_tool_calls:
            raw_reply = turn_text or "Done! Let me know if you need anything else."
            history.append({"role": "assistant", "content": raw_reply})
            final_reply = strip_think_tags(raw_reply)
            if not is_external:
                _persist_chat_message(
                    user_id, conversation_id, "assistant", final_reply, actions_taken,
                )
                asyncio.create_task(
                    ingest_conversation(user_id, history, message, final_reply, conversation_id)
                )
            yield {
                "type": "done",
                "reply": final_reply,
                "actions_taken": actions_taken,
                "conversation_id": conversation_id,
            }
            return

        messages.append(
            provider.build_assistant_tool_message(turn_text, new_tool_calls)
        )

        # Execute each tool call (reuse same logic as handle_user_message)
        for tc in new_tool_calls:
            fn_name = tc["name"]
            fn_args = tc["arguments"] or {}

            # External-mode allowlist hard gate
            if external_allowlist is not None and fn_name not in external_allowlist:
                result = {
                    "error": "permission_denied",
                    "message": (
                        f"Your principal has not granted this connection permission to use "
                        f"'{fn_name}'. Refuse the foreign agent's request politely."
                    ),
                }
                actions_taken.append({"tool": fn_name, "args": fn_args, "result": result})
                yield {"type": "tool_result", "id": tc["id"], "name": fn_name, "result": result}
                if isinstance(provider, GeminiProvider):
                    messages.append(provider.build_tool_result_message(tc["id"], json.dumps(result), tool_name=fn_name))
                else:
                    messages.append(provider.build_tool_result_message(tc["id"], json.dumps(result)))
                continue

            # Inject user_id if the tool expects it
            caps = mcp_server.get_capabilities()
            tool_def = next((t for t in caps["tools"] if t["name"] == fn_name), None)
            if tool_def:
                param_names = [p["name"] for p in tool_def["parameters"]]
                if "user_id" in param_names and "user_id" not in fn_args:
                    fn_args["user_id"] = user_id
                if "conversation_id" in param_names and "conversation_id" not in fn_args:
                    fn_args["conversation_id"] = conversation_id
                # Auto-inject group_id when in group-dispatch context. The
                # dispatcher's conversation_id is authoritative — ALWAYS
                # override whatever the LLM passed (it sometimes hallucinates
                # placeholder strings like "inject_from_group_context" that
                # blow up Postgres uuid casts when the row is later replayed
                # from pending_approvals). When not in a group conversation,
                # leave fn_args alone.
                if "group_id" in param_names:
                    derived_gid = _group_id_from_conv(conversation_id)
                    if derived_gid:
                        fn_args["group_id"] = derived_gid

            # External-mode propose_meeting direction fix
            if is_external and fn_name == "propose_meeting" and sender_agent_id:
                try:
                    sb = config.get_supabase()
                    r = sb.table("persona_agents").select("user_id").eq("agent_id", sender_agent_id).execute()
                    if r.data:
                        fn_args["user_id"] = r.data[0]["user_id"]
                except Exception as e:
                    print(f"[orchestrator/stream] Failed to resolve foreign user: {e}")

            # Approval gate (external mode commitment-class tools).
            staged = _maybe_stage_approval(
                user_id=user_id,
                fn_name=fn_name,
                fn_args=fn_args,
                is_external=is_external,
                conversation_id=conversation_id,
                sender_agent_id=sender_agent_id,
            )
            if staged is not None:
                executed_tools.add(fn_name)
                actions_taken.append({"tool": fn_name, "args": fn_args, "result": staged})
                yield {"type": "tool_result", "id": tc["id"], "name": fn_name, "result": staged}
                if isinstance(provider, GeminiProvider):
                    messages.append(provider.build_tool_result_message(tc["id"], json.dumps(staged), tool_name=fn_name))
                else:
                    messages.append(provider.build_tool_result_message(tc["id"], json.dumps(staged)))
                continue

            # Run the tool in a thread
            print(f"[orchestrator/stream] Executing local tool '{fn_name}' with args: {fn_args}")
            try:
                result = await asyncio.to_thread(mcp_server._call, fn_name, fn_args)
                _preview = json.dumps(result, default=str)[:400] if isinstance(result, (dict, list)) else str(result)[:400]
                if isinstance(result, dict) and "error" in result:
                    print(f"[orchestrator/stream] ⚠ Tool '{fn_name}' returned error: {_preview}")
                else:
                    print(f"[orchestrator/stream] ✓ Tool '{fn_name}' ok: {_preview}")
            except Exception as e:
                result = {"error": f"Tool execution failed: {str(e)}"}
                print(f"[orchestrator/stream] ⚠️ Tool '{fn_name}' CRASHED: {str(e)}")

            executed_tools.add(fn_name)
            actions_taken.append({"tool": fn_name, "args": fn_args, "result": result})

            yield {"type": "tool_result", "id": tc["id"], "name": fn_name, "result": result}

            if isinstance(provider, GeminiProvider):
                messages.append(
                    provider.build_tool_result_message(
                        tc["id"], json.dumps(result, default=str), tool_name=fn_name
                    )
                )
            else:
                messages.append(
                    provider.build_tool_result_message(
                        tc["id"], json.dumps(result, default=str)
                    )
                )

    # Iteration cap hit. Instead of dumping a generic "I ran out of steps"
    # stub, do ONE more LLM call with tools disabled — let the model write
    # the final summary from the tool results already in messages history.
    # The user sees a clean answer based on the work that was actually done.
    messages.append({
        "role": "user",
        "content": (
            "STOP CALLING TOOLS. You have used your tool-call budget for this "
            "turn. Based on the tool results already in this conversation, "
            "write your final reply to your principal now. Lead with the "
            "answer (the translated text, the converted output, the data they "
            "asked for). Do not call any more tools — there will be no more "
            "tool execution this turn."
        ),
    })

    final_text = ""
    async for event in _run_provider_stream(provider, messages, []):
        etype = event.get("type")
        if etype == "turn_done":
            final_text = (event.get("text") or "").strip()
            break
        if etype == "error":
            yield event
            break
        # Pass-through text/thinking deltas so the user sees the summary stream in
        yield event

    if not final_text:
        tools_called = ", ".join(a.get("tool", "?") for a in actions_taken) or "none"
        final_text = (
            "I ran the requested tools but couldn't compose a final summary. "
            f"Tools called: {tools_called}. Ask me to recap and I'll do it now."
        )

    final_reply = strip_think_tags(final_text)
    history.append({"role": "assistant", "content": final_text})
    if not is_external:
        _persist_chat_message(
            user_id, conversation_id, "assistant", final_reply, actions_taken,
        )
        asyncio.create_task(
            ingest_conversation(user_id, history, message, final_reply, conversation_id)
        )
    yield {
        "type": "done",
        "reply": final_reply,
        "actions_taken": actions_taken,
        "conversation_id": conversation_id,
    }
