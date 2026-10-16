---
name: zynd-context
description: Recall relevant private ZYND context when the user asks about remembered information or it materially helps the current request; do not load at every chat start.
---

# ZYND context

Call `get_my_context` only when the request needs the user's remembered
context; do not fetch it automatically at conversation start. Use `topic` to
focus returned facts when useful (`k` is bounded to 1..50). Only use tools
visible on the connected ZYND MCP server; packaged instructions do not grant
server permissions or import runtime `skill://` resources.

The result is bounded, not a complete export. `identity` alone is not evidence
of stored facts. A null optional section may be unavailable rather than empty;
an empty topic-filtered `facts` list does not prove no facts exist. Render the
returned `statement` for each fact rather than raw predicate or confidence.
Keep `facts`, `profile`, and `brief` private: only `card` is evidence of public
approved facts. `status` and `activity` are owner sections that may be omitted
or unavailable. Do not invent remembered facts or claim unavailable data is
empty. If a durable new fact emerges, follow `zynd-memory` and ask before
storing it.
