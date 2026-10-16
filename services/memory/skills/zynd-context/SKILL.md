---
name: zynd-context
description: Recall what ZYND knows about the user and put it to work. Use at the start of a conversation, when answering questions about the user, or when the user's stored profile would make an answer better.
---

# ZYND Context — Know Who You're Helping

`get_my_context` is the single self-info read tool. Use only tools visible in
the client's actual tool list; do not look for another self-info read tool.

## When to load context

- **Start of every conversation** — call `get_my_context` before the first
  answer so you know the user's role, projects, skills, and goals.
- Topic-aware: pass `topic` ("What are they building?") to focus `facts` on the
  question at hand. `k` defaults to 20 and is bounded to 1..50; topic does not
  filter identity, profile, socials, brief, or card.

## How to read the results

- The bounded packet contains `identity`, `profile`, `socials`, `brief`, `facts`,
  `card`, and `present`. It is not an exhaustive graph export.
- Address the user by `identity.name`, which is always non-empty. It may be an
  email-derived or generic display label, not a verified real name. `identity.email`
  may be null. A linked Persona name can fill an empty stored display name on
  read; this best-effort self-heal preserves an existing explicit name.
- `profile` is the normalized Persona profile; `socials` prefers Persona links
  with stored links as fallback. `brief` is the user's private brief.
- `present` lists sections with substantive content. Identity is always listed,
  but identity alone does not mean useful stored context or facts exist. If the
  available sections are empty, invite the user to share durable facts to save
  through `report_user_info`.
- A null profile or brief can mean unset or unavailable, not proof that the user
  has no information. Empty arrays indicate no returned facts in that section;
  a topic-filtered empty `facts` array does not prove the whole graph is empty.
- `status` and `activity` are included only for `cards:read` or legacy `user`
  scope. Omitted owner keys mean no read access; null means disabled or unavailable.
- Only `get_my_context.card` shows approved public facts. `facts`, `profile`,
  and `brief` are private context, not evidence of public visibility.
- Each entry in `get_my_context.facts` carries a natural-language `statement`
  (e.g. "You're building a micro-SaaS"). Show the `statement` text to the user.
- Do NOT surface raw predicate/confidence values — they're internal.
- Only report what the tool actually returns; never invent remembered facts.

## Personalization

- Use the loaded facts to tailor answers: their stack, their projects, their
  goals — reference them naturally.
- Ask before storing new durable facts they reveal mid-conversation, then call
  `report_user_info` (see the `zynd-memory` skill).

## People and networking (when the user asks)

- `find_similar_users` — people with overlapping context ("people like me").
- `find_people` — a target profile ("seed-stage investors in dev tools").
- `search_linkedin_profiles` / `find_linkedin_people_for_me` — LinkedIn search
  enriched with profiles; ZYND users rank first.

## Verification

- If the user confirms a fact: `confirm_fact_tool` with the exact predicate
  and object from `get_my_context.facts`.
- If they say a fact is wrong/private/outdated: `forget_fact_tool` with the exact
  predicate and object from `get_my_context.facts`. Never claim a correction
  succeeded when the tool reports failure.
- `export_my_context` only for an explicit backup, download, or export request,
  and only if visible in the client's tool list.
