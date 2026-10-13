---
name: zynd-card
description: The user's public ZYND card — what's public, what's pending review, and how the owner approves facts. Use when the user asks about their card, their public profile, or reviewing what AIs have stored about them.
---

# ZYND Card — Public Profile and Fact Review

Every fact ZYND stores starts private. The user reviews facts on their card;
only approved facts become publicly discoverable. This skill covers both sides.

## What is public

- `get_my_card` — the facts the user approved for public discovery.
- `get_my_card` is the only source of truth for "what is public about me" —
  never assume a stored fact is public.

## Owner review flow

- `get_card_status` — card completeness, review count, sources, owner actions.
- `get_card_activity` — last seven days of card views and agent hits.
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

## Related skills

- `zynd-memory` — what to store and what not to store.
- `zynd-context` — recall and use what ZYND knows.