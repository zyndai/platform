---
name: zynd-card
description: The user's public ZYND card — what's public, what's pending review, and how the owner approves facts. Use when the user asks about their card, their public profile, or reviewing what AIs have stored about them.
---

# ZYND Card — Public Profile and Fact Review

Every fact ZYND stores starts private. The user reviews facts on their card;
only approved facts become publicly discoverable. This skill covers both sides.

## What is public

- Call `get_my_context` and inspect `get_my_context.card` for facts the user
  approved for public discovery. This is the only source of truth for "what is
  public about me"; `facts`, `profile`, and `brief` are private context.
- An empty `card` means no approved public facts were returned. Identity alone
  does not establish stored facts or public content; null optional sections
  indicate unset or unavailable data, not proof that there is no information.

## Owner review flow

- `get_my_context.status` — card completeness, review count, sources, owner actions.
- `get_my_context.activity` — last seven days of card views and agent hits (a dict).
- Both owner sections require `cards:read` or legacy `user` scope, not merely
  `cards:approve`. Without read access they are omitted and no owner lookup is
  made; with read access they are null when disabled or unavailable. Null is
  not a known count of zero.
- `list_pending_facts` — the review inbox of facts waiting for a decision.
- `approve_fact` — publish a fact to the public card (requires the user's
  explicit confirm; suggest only what they asked to publish).
- `dismiss_fact` — keep a fact private/remove it from review.
- `set_looking_for` — what the user is open to (investors, cofounders, …).

## Rules

- Never approve or publish anything the user did not explicitly ask to make
  public — approval needs their confirmation.
- Facts stay private until reviewed: say that when new facts are saved.
- If approval is refused by the tool (missing confirmation/scope), report the
  reason instead of retrying.
- Use only tools visible in the client's actual tool list and granted scopes.
- For private fact corrections, use `confirm_fact_tool` or `forget_fact_tool`
  with exact predicate and object from `get_my_context.facts`; do not confuse
  confirmation with public approval or claim success on a false result.

## Related skills

- `zynd-memory` — what to store and what not to store.
- `zynd-context` — recall and use what ZYND knows.
