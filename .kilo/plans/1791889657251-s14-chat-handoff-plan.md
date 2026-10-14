# S14 remainder: hand-off, prompts, abuse filter, topic counts

Honest assistant disclosure, CardView facts, claimed-only chat, and the 12/min rate limit already ship in `services/cards-api/api/chat.py` and `ProfileChatWidget.tsx`. Do not add `FEATURE_S14_ASSISTANT_V2` and do not put the disclosure behind a flag.

No schema migration. Topic consent is a settings caption, not a new `notification_prefs` key. `Preferences` replaces the whole jsonb on PATCH; a new key would be wiped or would need a migration, and categories are not message text.

## Decisions

- Hand-off is UI, not another model instruction. Booking URLs already go into the prompt. Buttons must not depend on the model emitting a link.
- Intro button only when S12 says the card can take an intro. `RequestIntro` already hides itself when `/intro-eligibility` is false.
- Suggested prompts are static strings from public card fields. Clicking one sends it as a normal user message.
- Abuse filter is local and dumb: length, count, and a few block patterns. No moderation API. Rejected text is not stored and not echoed.
- `chat_message` meta gains `chars` and `category` only. Owner home shows category counts beside the existing S11 "Questions that found your card" list. Do not mix them. Do not add categories to the weekly digest.

## 1. Cards API — abuse filter and event meta

File: `services/cards-api/api/chat.py`.

Order inside `chat`: config check, load card, unclaimed 403, rate limit, abuse filter, emit, then stream.

Abuse filter on `body.messages` before any LLM call:

- 1–8 messages. Each `role` is `user` or `assistant`. Each `content` is a string.
- Last message is `user`. Its stripped length is 1–1000.
- Reject the last user message if it contains an email, a 10+ digit phone-like run, or any of: `ignore previous`, `system prompt`, `api key`, `owner_email`. Case-insensitive.
- On failure return 400 `{"detail": "That question can't be sent."}`. Do not include the message. Do not emit.

Category of the last user message, keyword, first match:

| Category | If the text contains |
|---|---|
| `contact` | contact, email, call, meet, book, intro, calendly, linkedin |
| `work` | build, building, project, working |
| `skills` | skill, good at, help, expert |
| `background` | who, where, based, about |
| `other` | anything else |

Emit stays `chat_message` with `meta={"chars": <int>, "category": <one of the five>}`. Drop the current `meta.handle` duplicate. `chars` is the stripped length, never the text. `emit` is already a no-op when `FEATURE_S04_EVENTS` is off; leave that.

Prompt change is test-only in spirit: keep the existing disclosure lines. Add one assertion path that a stuffed `owner_email`, token, or unapproved memory blob on the card dict never appears, because `_build_system_prompt` only copies the public fields and `memory_facts`.

## 2. Owner home — topic counts

Files: `services/cards-api/services/owner_home.py`, `api/owner_home.py` only if the status payload is assembled there (it is inside `owner_home.status` via `activity`).

`activity()` adds `chat_topics: [{category, count}]`, last 7 days, from `card_events` where `event=chat_message`. Read `meta.category` only. Ignore missing or unknown categories. Order by count desc. Cap at the five known labels.

Do not change `query_summaries`. That list is S11 `agent_fetch` text and must stay separate.

Empty when events are disabled: `chat_topics: []`, same as today's empty `queries`. No new flag.

## 3. Web — widget

File: `apps/cards-web/src/components/ProfileChatWidget.tsx`.

New optional props:

- `prompts: string[]` (max 3)
- `bookingLinks: {label: string; url: string}[]`
- no intro boolean from the server

Empty state, under the existing AI disclaimer:

- Render `prompts` as buttons. Click sets the input and calls the same `send` path (extract `sendText(text)` so chips do not depend on input state).
- One more chip, `How do I contact them?`, only when `bookingLinks.length > 0` or an intro is ready. It sends that sentence.

Hand-off row, above the textarea, after at least one user message whose text matches the contact keywords (same list as the API `contact` category):

- One link per booking URL: `Book on Calendly` / `Book on Google Calendar`. `target=_blank`, `rel=noopener noreferrer`. Use the existing `safeUrl` results from the page; the widget does not re-validate beyond requiring `https?:`.
- `Request an intro` only after `window` event `zynd:intro-ready`. Click dispatches `zynd:open-intro`.
- If there is no booking link and intro is not ready, render nothing. Do not invent a contact method.

Error bubbles stay as they are. 429 already arrives as `Too many questions — please slow down` from `app/api/chat/profile/route.ts`.

## 4. Web — profile, welcome, intro, owner home

`apps/cards-web/src/app/(site)/p/[handle]/page.tsx`

Pass into `ProfileChatWidget`:

- `bookingLinks` — the array already built near line 484.
- `prompts` — up to 3, skip blanks:
  - `working_on[0]` → `What is ${firstName} building?`
  - `skills[0]` → `What is ${firstName} good at?`
  - headline → `What does ${firstName} do?`
- Still render the widget only when `claimed`.

`apps/cards-web/src/components/intros/RequestIntro.tsx`

- When `available` becomes true, dispatch `zynd:intro-ready`.
- Listen for `zynd:open-intro`: `setOpen(true)` and `scrollIntoView`. Ignore the event when `available` is false.
- Welcome page does not mount `RequestIntro`, so the owner's first-win chat never shows the intro button.

`apps/cards-web/src/app/(site)/p/[handle]/welcome/page.tsx`

Pass the same `prompts` and `bookingLinks` when `claimed`. No intro wiring.

`apps/cards-web/src/app/(site)/home/owner-home.tsx` and `src/lib/owner-home.ts`

- Add `chat_topics: {category: string; count: number}[]` on `activity`.
- Under the existing questions list, add **What people asked the assistant**. Map codes to labels: Contact, Work, Skills, Background, Other. Show `count`. Empty copy: `No assistant questions recorded yet.`
- In the Visibility & emails section, add a caption: `The public assistant records the topic of each question, such as contact or work, and how long it was. It does not store the question text.`
- Do not add a toggle.

## 5. Tests

`services/cards-api/tests/` (extend `test_chat_cardview.py` or add `test_chat_s14.py`):

- Prompt built from a card dict that also has `owner_email`, a fake token, and an unapproved fact string not passed via `memory_facts`: none of those strings appear. Approved fact still appears.
- 13th call with the same `x-forwarded-for` returns 429 and `slow down`.
- 1001-character user message and a message containing an email return 400 with the generic detail and no echo of the input.
- Emit spy: meta is exactly `chars` + `category`, and the user text is absent. A "book a call" message is `contact`.
- `activity()` fixture with two `chat_message` rows returns grouped `chat_topics` and does not change `queries`.

No new web test harness. Typecheck is the web check: `cd apps/cards-web && npx tsc --noEmit`.

API: `cd services/cards-api && pytest -q tests/test_chat_cardview.py tests/test_chat_s14.py tests/test_owner_home.py tests/test_unclaimed_tiering.py`. Known baseline failures in the full suite are unrelated; these files should be clean.

## Out of scope

- Replacing chat with the persona orchestrator.
- Weekly digest copy for chat topics.
- Storing or showing raw visitor questions.
- A new feature flag or a `notification_prefs` migration.
