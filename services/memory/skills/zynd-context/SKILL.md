---
name: zynd-context
description: Recall what ZYND knows about the user and put it to work. Use at the start of a conversation, when answering questions about the user, or when the user's stored profile would make an answer better.
---

# ZYND Context — Know Who You're Helping

Your window into the user is `get_my_context`. Without it you answer blind.

## When to load context

- **Start of every conversation** — call `get_my_context` before the first
  answer so you know the user's role, projects, skills, and goals.
- Topic-aware: pass `topic` ("What are they building?") to get the K most
  relevant facts for the question at hand.
- If the profile is empty, tell the user to share facts so you can call
  `remember` — the graph only fills when they feed it.

## How to read the results

- Each fact carries a natural-language `statement` (e.g. "You're building a
  micro-SaaS"). Show the `statement` text to the user.
- Do NOT surface raw predicate/confidence values — they're internal.
- Only report what the tool actually returns; never invent remembered facts.

## Personalization

- Use the loaded facts to tailor answers: their stack, their projects, their
  goals — reference them naturally.
- Ask before storing new durable facts they reveal mid-conversation, then call
  `remember` or `report_user_info` (see the `zynd-memory` skill).

## People and networking (when the user asks)

- `find_similar_users` — people with overlapping context ("people like me").
- `find_people` — a target profile ("seed-stage investors in dev tools").
- `connect_with` — send a connection request to a returned `user_id`.
- `my_connections` / `send_persona_message` — existing connections and DMs.
- `search_linkedin_profiles` / `find_linkedin_people_for_me` — LinkedIn search
  enriched with profiles; ZYND users rank first.

## Verification

- If the user confirms a fact: `confirm_fact_tool` with the exact predicate
  and object from `get_my_context`.
- If they say a fact is wrong/private/outdated: `forget_fact_tool`.
- `export_my_context` when they want a full backup or inspection.