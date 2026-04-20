"""
Agent Orchestrator — the brain of the system.

Takes a user message, figures out what tool(s) to call via the MCP
server, executes them, and returns a natural-language response.

Supports OpenAI, Google Gemini, and Custom OpenAI-compatible endpoints.
The provider is chosen via the LLM_PROVIDER env var:
  "openai"  — official OpenAI API
  "gemini"  — Google Gemini via google-genai SDK
  "custom"  — any OpenAI-compatible endpoint (base_url + api_key + model)

All tool execution is routed through the ContextAware `_call` method.
"""

import asyncio
import json
import uuid

import config
from mcp.server import mcp_server
from services.token_store import list_connected_providers

# ── Conversation memory (in-memory; move to Supabase for persistence) ─
_conversations: dict[str, list[dict]] = {}


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
    "search_zynd_personas",
    "get_persona_profile",
    "list_my_connections",
    "check_connection_status",
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
    },
    # `can_view_full_profile` doesn't gate tools; it only gates the persona
    # briefing rendered into the system prompt (handled in _format_user_brief).
}


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
    """Remove all <think>...</think> blocks from a string (for non-streaming paths)."""
    import re
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


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

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None):
        from openai import OpenAI
        kwargs = {}
        if base_url:
            kwargs["base_url"] = base_url
            # Bypass Cloudflare WAF bot blocking if using a custom mapped domain
            kwargs["default_headers"] = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) width/1920"}
            
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
            return choice.message.content or "", None

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

        yield {
            "type": "turn_done",
            # RAW text (with <think> tags) — orchestrator stores this in
            # history and strips for the user-facing reply.
            "text": "".join(raw_text_parts),
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
                    "parameters": {
                        "type": "object",
                        "properties": t["properties"],
                        "required": t.get("required", []),
                    },
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
        function_calls = []
        text_parts = []
        for part in candidate.content.parts:
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                function_calls.append({
                    "id": fc.id if hasattr(fc, "id") else str(uuid.uuid4()),
                    "name": fc.name,
                    "arguments": dict(fc.args) if fc.args else {},
                })
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
                    tool_calls.append({"id": tc_id, "name": name, "arguments": args})
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
                        parts.append(types.Part.from_function_call(
                            name=tc["name"],
                            args=tc.get("arguments", {}),
                        ))
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

def _format_user_brief(persona: dict, redact_profile: bool = False) -> str:
    """
    Render the principal's profile/description as a 'who you serve' briefing.

    When `redact_profile` is True (used in external mode when the calling
    connection does NOT have can_view_full_profile), only the description
    is included — title, org, location, interests, and social links are
    stripped so the foreign agent learns nothing beyond what's already on
    the public registry card.
    """
    desc = persona.get("description") or ""
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


def _build_system_prompt(
    user_id: str,
    connected_providers: list[str],
    is_external: bool = False,
    sender_agent_id: str | None = None,
    external_permissions: dict | None = None,
) -> str:
    """Build a system prompt that tells the agent what it can do."""
    tools_prompt = mcp_server.get_tools_prompt()
    providers_str = ", ".join(connected_providers) if connected_providers else "none"

    from agent.persona_manager import get_persona_status
    persona = get_persona_status(user_id)
    principal_name = persona.get("name", "the user")
    agent_handle = persona.get("agent_handle")  # may be None
    capabilities = persona.get("capabilities", [])

    # In external mode, redact profile fields if the foreign side doesn't
    # have can_view_full_profile. The principal's name and description are
    # always visible (those are already on the public card), but title,
    # organization, location, interests and social links are gated.
    redact = is_external and not (external_permissions or {}).get("can_view_full_profile", False)
    user_brief = _format_user_brief(persona, redact_profile=redact)

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

Use this as factual background about the human you serve. Do not adopt their identity, do not claim to be them, do not speak in their voice as if you are them. You are their agent, not them."""

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

## Available Tools
{tools_prompt}

## Meeting Proposals (external mode)
If the foreign agent is asking to schedule a meeting, and `propose_meeting` is in your allowlist above:
  - You MAY call `propose_meeting` to formally request a meeting with your principal. The proposal will create a ticket your principal sees in their inbox; they decide whether to accept, counter, or decline.
  - Be concrete about the requested time (ISO-8601 UTC) and include a clear title.
  - Do NOT try to accept or finalize a meeting yourself — only the principal can act on incoming proposals.
If `propose_meeting` is NOT in your allowlist, refuse any scheduling request politely, explaining that the principal has not granted this connection permission to request meetings.

## Rules
1. When calling a tool, ALWAYS pass the `user_id` parameter as "{user_id}".
2. ONLY call tools in the per-thread allowlist above. Anything else WILL be blocked.
3. Keep your reply brief, professional, and clearly framed as coming from the agent (not the principal).
4. When refusing, be polite and concrete: name what was asked, name the missing permission, and offer an alternative if you can.
"""

    # ── Internal mode: chatting directly with the principal ──────────
    return f"""{identity_preamble}

## Current Conversation
You are currently in a private chat WITH your principal — the human who deployed you. In this conversation:
  - "You" (second person) refers to the principal you are talking to.
  - "I" (first person) refers to yourself, the AI agent.
  - Your job is to help them network, manage their accounts, and act on their requests.
  - Do not claim to be them. If they say "what's my next meeting", you look it up and report back as their agent — you don't pretend to be them.

## Your Job
PRIMARY: Help your principal network on the Zynd AI Network — discover other people's agents, look up their profiles, connect with them, and exchange messages on your principal's behalf.
SECONDARY: Manage your principal's connected accounts (social media, calendar, email, productivity tools) when they ask.

## Networking Strategy
When your principal asks about a person, company, or topic:
1. FIRST search the Zynd Network with `search_zynd_personas` — this is your primary discovery tool.
2. If you find relevant personas, present them with name, description, and agent_id.
3. Offer to view a full profile (`get_persona_profile`) or initiate a connection (`request_connection`).
4. THEN supplement with `internet_search` only if your principal wants broader information beyond the network.
5. Always prioritize network results — these are real agents your principal can actually interact with.

When your principal asks to connect, message, or interact with someone:
1. First check if they're already connected (`check_connection_status` or `list_my_connections`).
2. If not connected, search and offer to send a connection request.
3. If connected, send the message via the other agent's webhook.

## Connected Accounts
Your principal currently has these accounts connected: {providers_str}

## Available Tools
{tools_prompt}

## Meeting Scheduling Protocol
When your principal asks you to schedule a meeting with someone:
1. First check that you have an accepted connection with them (`check_connection_status` or `list_my_connections`). You CANNOT propose a meeting on a thread that isn't accepted yet — if it's still pending, tell your principal to wait for the other side to accept the connection request first.
2. Negotiate availability by sending a message to the other agent via `message_zynd_agent` on the accepted thread. Ask an open question like "when is your principal free next week?".
3. When the other agent replies with candidate times, STOP and bring the options back to your principal in plain text. Example: *"Alice is free Tuesday 2-4pm or Friday 10am. Which slot should I book?"*
4. Wait for your principal's explicit confirmation of a specific start and end time. Do NOT guess. Do NOT pick one yourself.
5. ONLY THEN call `propose_meeting(thread_id, title, start_time, end_time, ...)` to formalise the ticket. This writes a proper record both sides can see, and the UI renders it as an acceptable/declinable card.
6. The `thread_id` must match the dm_thread you've been negotiating on — get it from `list_my_connections` if you don't already have it.
7. All times must be ISO-8601 UTC (e.g. "2026-04-14T15:00:00Z"). Convert the principal's local-time phrasing to UTC before calling.
8. If your principal asks "what meetings am I expecting?" or "do I need to respond to anything?", use `list_pending_meetings`. If they ask you to accept / decline / reschedule a specific ticket, use `respond_to_meeting`.
9. Never auto-accept a meeting on your principal's behalf without them telling you to.

## Rules
1. When calling a tool, ALWAYS pass the `user_id` parameter as "{user_id}".
2. If your principal requests an action on a platform that's not connected, politely ask them to connect it first via the dashboard.
3. Be concise but helpful. After performing an action, confirm what was done.
4. When scheduling calendar events, always confirm the date/time with your principal before creating.
5. For tweets, respect the 280 character limit.
6. NEVER call the same tool more than once in a single turn unless your principal explicitly asks for multiple actions.
7. After a tool executes, you MUST summarize the result in detail. If the tool returns a list, list out the names/details so your principal can see them.
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

    # Build messages
    system_msg = {
        "role": "system",
        "content": _build_system_prompt(
            user_id,
            connected,
            is_external,
            sender_agent_id,
            external_permissions=external_permissions,
        ),
    }
    print("System Prompt: ", system_msg)
    user_msg = {"role": "user", "content": message}
    history.append(user_msg)

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

    # LLM loop — keep going until the model produces a final text response
    # Multi-step workflows like "search → check → message → summarize" need
    # at least N+1 iterations: one per tool call plus a final iteration where
    # the LLM produces the text response that wraps up for the user. With 3
    # we hit the cap before the wrap-up and fall through to the generic
    # fallback message. 6 gives comfortable headroom for chained tool flows.
    max_iterations = 6
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
            return {
                "reply": strip_think_tags(raw_reply),
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
            return {
                "reply": strip_think_tags(raw_reply),
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

            # External-mode propose_meeting direction fix: when a foreign
            # agent asks us to formalize a meeting, the proposal should be
            # *from* their user *to* our user (we're the recipient, they're
            # the initiator). Without this override, the auto-injected
            # user_id makes US the proposer, which inverts the direction.
            if is_external and fn_name == "propose_meeting" and sender_agent_id:
                try:
                    from supabase import create_client
                    sb = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
                    r = sb.table("persona_agents").select("user_id").eq("agent_id", sender_agent_id).execute()
                    if r.data:
                        foreign_user_id = r.data[0]["user_id"]
                        fn_args["user_id"] = foreign_user_id
                        print(f"[orchestrator] propose_meeting external: overriding user_id → {foreign_user_id} (foreign proposer)")
                except Exception as e:
                    print(f"[orchestrator] Failed to resolve foreign user for propose_meeting: {e}")

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

    # Fallback if we hit max iterations. We make the message specific so the
    # user knows we ran out of room to summarize and can ask for a recap.
    tools_called = ", ".join(a.get("tool", "?") for a in actions_taken) or "none"
    return {
        "reply": (
            "I performed the requested actions but ran out of reasoning steps before I could "
            "summarize the results for you. Tools I called this turn: "
            f"{tools_called}. Ask me to summarize the latest result and I'll do it now."
        ),
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

    system_msg = {
        "role": "system",
        "content": _build_system_prompt(
            user_id,
            connected,
            is_external,
            sender_agent_id,
            external_permissions=external_permissions,
        ),
    }
    user_msg = {"role": "user", "content": message}
    history.append(user_msg)
    messages = [system_msg] + history

    tools = _capabilities_to_generic_tools()
    external_allowlist: set[str] | None = None
    if is_external:
        external_allowlist = _allowed_external_tools(external_permissions)
        tools = _filter_tools_by_allowlist(tools, external_allowlist)

    provider = _get_provider()

    actions_taken: list[dict] = []
    executed_tools: set = set()

    max_iterations = 6
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
            yield {
                "type": "done",
                "reply": strip_think_tags(raw_reply),
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
            yield {
                "type": "done",
                "reply": strip_think_tags(raw_reply),
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

            # External-mode propose_meeting direction fix
            if is_external and fn_name == "propose_meeting" and sender_agent_id:
                try:
                    from supabase import create_client
                    sb = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
                    r = sb.table("persona_agents").select("user_id").eq("agent_id", sender_agent_id).execute()
                    if r.data:
                        fn_args["user_id"] = r.data[0]["user_id"]
                except Exception as e:
                    print(f"[orchestrator/stream] Failed to resolve foreign user: {e}")

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

    # Fallback: hit the iteration cap
    tools_called = ", ".join(a.get("tool", "?") for a in actions_taken) or "none"
    fallback = (
        "I performed the requested actions but ran out of reasoning steps before I could "
        f"summarize. Tools called: {tools_called}. Ask me to summarize and I'll do it now."
    )
    yield {
        "type": "done",
        "reply": fallback,
        "actions_taken": actions_taken,
        "conversation_id": conversation_id,
    }
