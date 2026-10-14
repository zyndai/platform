---
name: zynd-memory
description: Two-way ZYND memory flow — when to store durable facts about the user and when NOT to store. Use whenever the user shares something durable about themselves (role, skills, projects, goals) or asks about saving things to memory.
---

# ZYND Memory — What to Store and What Not to Store

ZYND is the user's cross-AI memory. It works only if you feed it the right
things and skip the wrong ones. This skill is the store/not-store rulebook.

## The two-way flow

1. **FEED** — when the user shares a durable fact, call `report_user_info`:
   `text` for a single free-text fact, or typed fields for structured facts
   (skills, languages, frameworks, tools, projects, goals, role, notes).
2. **READ** — at the start of every conversation, call `get_my_context` so you
   know who the user is before answering.

Saving grows the memory graph; reading lets you use its context.

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
- Use `report_user_info(text="...")` for a single free-text fact stated in one
  sentence. Supply `text` alone, without non-empty typed fields.
- The two modes are mutually exclusive: non-blank `text` combined with any
  non-empty typed field is rejected before saving. Blank or whitespace-only
  `text` uses the typed mode; never rely on a mixed call to discard an input.
- Report at milestones, not continuously: end of a meaningful session, after
  learning a durable skill, when a project ships or goals change. Never call
  on every keystroke or every file edit.
- Batch several facts into one `report_user_info` call instead of five calls.
- Facts stay private until the user reviews them on their card — say so when
  saving, and never claim something was saved unless the tool returned
  `saved: true`.
- Free-text extraction is asynchronous; a successful save need not appear in
  recall immediately. Report too-short or duplicate results honestly.

## Recall

- `get_my_context` — one bounded packet with identity, profile, socials, brief,
  facts, and card (pass a `topic` to focus facts). An identity-only packet is
  not evidence of stored facts; null optional sections can be unavailable,
  rather than empty. See `zynd-context` for packet interpretation.
- `get_my_context.card` — the only evidence of facts approved for public discovery;
  `facts`, `profile`, and `brief` remain private context.
- `export_my_context` — full JSON-LD export only for explicit backup/download/export.
- If the user says a stored fact is wrong: `forget_fact_tool` with the exact
  predicate and object from `get_my_context.facts`; if they confirm one:
  `confirm_fact_tool` with those same exact values. Never claim success on failure.

## Rules

- Never invent results — only report what the tools actually return.
- Use only tools visible in the client's actual tool list; export, brief, and
  social tools retain their existing legacy `user` scope requirement.
- If unsure whether something is durable, ask: "Want me to save this to ZYND?"
