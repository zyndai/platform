---
name: zynd-memory
description: Propose saving durable user facts to ZYND private memory and save only after explicit permission. Use when a user shares a lasting fact or asks to remember something.
---

# ZYND memory

This packaged skill is separate from server `skill://` resources. Use only tools
available on the connected ZYND MCP server; installation is not authorization.

- For a durable role, skill, project, or goal, propose the specific fact and ask
  permission to save it. Call `report_user_info` only after an explicit yes to
  that proposal. Never silently save a fact or infer a skill from a task.
- Never store passwords, keys, tokens, private file paths, one-off task details,
  or sensitive health, political, legal, immigration, or financial data. For
  other sensitive personal data, ask for specific consent before proposing a
  save; if uncertain, do not store it.
- Supply either a single full-sentence `text` or typed fields, not both. Use
  typed skills/languages/frameworks/tools only when explicitly stated. Batch
  only facts the user has approved. Facts start private, not on the public card.
- Say a save succeeded only when `saved: true`; mention duplicates, too-short
  text, or failure truthfully. Free-text extraction runs asynchronously, so
  do not promise immediate recall.
- If the user asks to verify or remove an existing private fact, first use
  `get_my_context` and pass its exact predicate and object to
  `confirm_fact_tool` or `forget_fact_tool`. Private confirmation does not
  publish anything. Report false results as failures, not success.
