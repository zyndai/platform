---
name: zynd-card
description: Inspect the user's public ZYND card and pending facts, then approve an exact pending fact only after a separate explicit confirmation from the user.
---

# ZYND card

- Call `get_my_context` when asked what is public; its `card` is the source
  for approved public facts. Private `facts`, `profile`, and `brief` are not
  evidence of public visibility. Null status/activity can mean unavailable.
- Call `list_pending_facts` to review private facts awaiting a decision.
  Present the exact fact in understandable language, retaining its returned
  predicate and object for the subsequent call. Never infer a pending fact.
- For each individual `approve_fact`, ask for and wait for a separate explicit
  yes to publishing that exact pending predicate/object to the public card.
  Only then pass the exact returned pair and `confirm: true`. A previous yes
  for a different fact or an instruction to publish everything is not enough.
  A model-supplied boolean alone is not proof of human consent: if the server
  lacks stronger confirmation binding, treat approval as an unverified step
  until the user explicitly confirms in the conversation. Report errors,
  revoked access, and missing scopes honestly; never retry without consent.
- `dismiss_fact` hides a pending fact from review; request confirmation of
  the exact pair before passing `confirm: true`. Do not conflate dismissal
  with deleting memory.
- `list_intros` reads inbound intros; human owners decide in the UI.
  `set_looking_for` may publish a recognized seeking value, otherwise it saves
  a private intent: describe that difference and ask before setting it.
  `update_headline` is a placeholder that returns `edit_on_card`; refer the
  user to the card editor and never claim it updated anything.
- `confirm_fact_tool` and `forget_fact_tool` act on private context with an
  exact predicate/object from `get_my_context.facts`; they do not approve a
  card fact. Use only visible tools and report their actual results.
