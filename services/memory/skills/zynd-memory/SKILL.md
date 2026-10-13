---
name: zynd-memory
description: Two-way ZYND memory flow — when to store durable facts about the user and when NOT to store. Use whenever the user shares something durable about themselves (role, skills, projects, goals) or asks about saving things to memory.
---

# ZYND Memory — What to Store and What Not to Store

ZYND is the user's cross-AI memory. It works only if you feed it the right
things and skip the wrong ones. This skill is the store/not-store rulebook.

## The two-way flow

1. **FEED** — when the user shares a durable fact, call `remember` (free text)
   or `report_user_info` (structured: skills, languages, frameworks, tools,
   projects, goals, role).
2. **READ** — at the start of every conversation, call `get_my_context` so you
   know who the user is before answering.

If either direction is skipped, the memory graph stays empty.

## STORE — durable professional facts

- Role and title ("I'm a backend engineer at Acme")
- Skills and programming languages ("I know Go and Postgres")
- Frameworks and tools they use ("we run FastAPI on AWS")
- Named projects they are building ("I'm building a travel app called Orbit")
- Goals ("I want to learn Rust", "I'm raising a seed round")
- Interests, affiliations, what they are learning or seeking

## DO NOT STORE — these pollute memory

- Secrets: API keys, passwords, tokens, `.env` contents, credentials — never
- Casual chatter and one-off task details ("rename this variable today")
- Repo names, local file paths, node_modules, internal session jargon
- Health, politics, immigration, legal, financial, or highly personal facts —
  ask the user first: "Want me to save this to your Zynd card memory?"

## How to store

- Use `report_user_info` for structured facts: put tools/languages/frameworks
  in the typed fields (they map to skills), projects in `projects`, goals in
  `goals`; keep `role` and `notes` free text.
- Use `remember` for a single free-text fact stated in one sentence.
- Report at milestones, not continuously: end of a meaningful session, after
  learning a durable skill, when a project ships or goals change. Never call
  on every keystroke or every file edit.
- Batch several facts into one `report_user_info` call instead of five calls.
- Facts stay private until the user reviews them on their card — say so when
  saving, and never claim something was saved unless the tool returned
  `saved: true`.

## Recall

- `get_my_context` — top facts about the user (pass a `topic` for relevance).
- `get_my_card` — only the facts the user approved for public discovery.
- `export_my_context` — full JSON-LD export on request.
- If the user says a stored fact is wrong: `forget_fact_tool` with the exact
  predicate and object from `get_my_context`; if they confirm one:
  `confirm_fact_tool`.

## Rules

- Never invent results — only report what the tools actually return.
- If unsure whether something is durable, ask: "Want me to save this to ZYND?"