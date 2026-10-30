# Zynd Companion — browser extension plan

| | |
|---|---|
| **Status** | Phase 1 built and tested on `feat/zynd-companion` (2026-10-27). Not applied anywhere: the migration (`cards` 0032) needs a human, and the extension is in no store. |
| **Scope** | Cards only: `apps/zynd-companion` (new), `apps/cards-web`, `services/cards-api`, `packages/db/cards`. Persona and `services/memory` are untouched. |
| **Origin** | The "Ambient Companion" requirement: the playbook's five-minute maintenance loop dies if updating a profile means opening cards.zynd.ai. |

## 1. What it is

A small Chromium (Chrome, Edge, Brave) extension. From any page, one click
puts something on the person's Zynd card without leaving the tab.

| Action | Where it lands on the card | Phase |
|---|---|---|
| Set **Working on** | `working_on` (the "Working On" section) | 1 |
| **Currently exploring** — a repo, paper, video, post, newsletter, blog or news article | new `exploring` list, shown on the card as "Currently exploring" | 1 |
| Remove either, from the popup | same fields | 1 |
| **Add a fact** to the Memory Card | memory service (`is_learning`, `is_building`, …) | 2 — needs a `services/memory` endpoint, see §8 |
| Import X (Twitter) bookmarks in bulk | `exploring` | 3 — needs X API access |

The requirement's source list is `youtube, blogs, newsletters, news articles,
twitter bookmark`. Phase 1 clips every one of those from the page the person
is on (a tweet is a "post"); only the bulk bookmark import waits.

## 2. Signed-in only, and how we know the account

The extension has no accounts of its own. It works only after it is **paired**
with a signed-in cards.zynd.ai session, and it shows the paired account
(name, handle, photo) in every popup so the account is never in doubt.

Pairing flow:

1. Popup, unpaired: the only control is **Connect Zynd account**. The
   extension makes a random `state`, stores it for 10 minutes, and opens
   `cards.zynd.ai/companion/connect?state=…`.
2. That page is server-gated: signed out → `/auth?next=…` (LinkedIn sign-in) →
   back. Signed in → it names the account and lists what the extension can and
   cannot do, with **Connect** / **Cancel**.
3. **Connect** calls `POST /cards/companion/pair` with the person's session. The
   API mints a random device token, stores only its SHA-256, and returns the
   token once.
4. The page hands `{state, token, profile}` to the extension through
   `postMessage`. The extension's only content script is matched to the connect
   page and drops the message unless the origin, source window and `state` all
   match what the extension is waiting for.
5. The token lives in `chrome.storage.local`. Nothing else is stored about the
   person except the profile summary used for the header.

Why a device token and not the website's own session:

- The Supabase session is the whole account. Copying it into an extension gives
  an extension bug the power to do anything the person can.
- Supabase refresh tokens rotate. Two clients sharing one get each other
  signed out. A separate credential avoids that outright.
- Reading the session cookie would die one hour after the last website visit
  (only a page load refreshes it), which defeats "no context switch".

The device token is accepted **only** by `/cards/companion/*`. The existing
Supabase-JWT paths never see it, and it cannot read messages, change identity,
touch settings or publish anything outside the two fields above. It is
revocable from the website (Connected devices on the connect page) and from the
popup (**Disconnect**, which also revokes server-side). It expires after 90 days
without use, which forces a fresh sign-in on the website for anyone who stops
using it.

**Decision for the owner:** signing out of the website does *not* disconnect
the extension. Doing so would mean the extension stops working whenever the
website session lapses, which is the friction this product removes. If you want
the strict version (website signed out ⇒ extension locked), it is a small
addition: a content script on cards.zynd.ai that tells the extension when the
session ends.

## 3. Privacy rules (these are requirements, not preferences)

- **Click only.** No passive reading, no browsing history, no background
  content scripts on ordinary pages. Page details are read once, when the
  person opens the popup on a tab (`activeTab` + `scripting`), and sent only
  after they press Add.
- **The person sees exactly what goes public** (title, link, kind, note) in the
  popup before it is sent. There is no silent capture and no auto-publish.
- **Never clip private pages.** `localhost`, private/loopback IPs, `.local` /
  `.internal` / single-label hosts, `file:`, `chrome:` and credentials in a URL
  are refused in the extension and again in the API (a clipped Jira or admin
  URL must not land on a public card).
- Tracking parameters (`utm_*`, `fbclid`, `gclid`, …) and fragments are removed
  before sending, and so are query parameters that carry a secret (`pwd`,
  `token`, `access_token`, `sig`, `code`, `state`, `X-Amz-*`, `X-Goog-*`, …),
  by the extension and again by the API. The popup shows the full address that
  will be published, query included.
- Incognito is off (Chrome's default for extensions; we do not ask for it).
- The API never fetches a clipped URL, so there is no SSRF surface.
- Least privilege: `activeTab`, `scripting`, `storage`, `contextMenus`,
  `alarms`; host access only to the Cards API. No `tabs`, no `<all_urls>`, no
  `cookies`, no `history`.

## 4. API (cards-api, `/cards/companion`)

| Route | Auth | Does |
|---|---|---|
| `POST /pair` | website session | Create a device, return its token once |
| `GET /devices` | website session | List the person's devices (no tokens) |
| `DELETE /devices/{id}` | website session | Revoke one |
| `POST /mine/exploring/remove` | website session | Remove one exploring item (the card editor's Interests tab; section saves cannot write `exploring`) |
| `GET /me` | device token | Header profile, current Working on, current exploring |
| `POST /working-on` | device token | Put one line on top; refused (422) once 20 are stored, never drops a line |
| `POST /working-on/remove` | device token | Remove one line |
| `POST /exploring` | device token | Add or bump an item; capped at 8 |
| `POST /exploring/remove` | device token | Remove one item |
| `POST /working-on/confirm` | device token | "Still working on this": the card page's confirm (503 before migration 0033) |
| `POST /disconnect` | device token | Revoke this device |

Writes go through a new `cards.companion_save_fields` SQL function: the same
row-locked compare-and-swap as `s10_save_section`, but allowed to touch only
`working_on` and `exploring`. If the website editor changed the same field in
between, the editor gets its normal "changed in another session" and the
extension retries once on the fresh value.

Public cards show an `exploring` item for 30 days after it was added, then
stop showing it (it stays stored). "Currently" should not outlive the person.

No new environment variables and no flags (AGENTS.md §9). Sizes, TTLs and caps
are named constants in `services/companion.py` (and `EXPLORING_VISIBLE_DAYS` in
`services/signals.py`, where public reads are derived). Remove routes are `POST`
because some proxies drop a `DELETE` body. Writes are rate limited per device
(20 a minute) and pairing per person (10 an hour), in-process like the other
cards-api limits: every write invalidates the card cache and revalidates the
page, and a Working on write also re-embeds the card.

## 5. Extension (`apps/zynd-companion`)

TypeScript, esbuild, no UI framework (the popup is a few hundred lines of DOM
code; a framework would be most of the bundle). vitest for the logic that
matters: URL cleaning, private-URL refusal, kind detection, the pairing
message check, API error mapping. Manifest V3.

Extras in Phase 1 (beyond the requirement), each cheap and aimed at the
"stale profile" problem:

- **Smart prefill.** The popup reads the tab's title, canonical URL, site and
  author, guesses the kind (repo / paper / video / post / newsletter / blog /
  news / link) and pre-selects it; one click changes it.
- **Right-click "Clip to Zynd profile"** on a page, link or selected text (the
  selection becomes the note).
- **Keyboard shortcut** (Alt+Shift+Z) opens the popup.
- **Freshness nudge.** If the person has not touched their card from the
  extension for 10 days, the toolbar icon gets a dot and the popup asks "Still
  working on this?" with Keep / Update. Keep also calls `POST /working-on/confirm`,
  so the card's own freshness resets; where the server cannot record it yet,
  only the local reminder resets. No notifications.
- **Undo and manage.** Recent clips and Working on lines are listed with a
  remove button, so a mistaken click is a five-second fix.

Roadmap, not built: memory facts (Phase 2), X bookmark import (Phase 3),
Firefox build (the code is WebExtension-clean; needs a `browser_specific_settings`
manifest and a test pass), a "Quiet hours" snooze for the nudge.

## 6. Files

- `apps/zynd-companion/` — the extension, README, tests, `npm run build`
- `services/cards-api/api/companion.py`, `services/companion.py`, tests
- `packages/db/cards/migrations/0032_companion_devices.sql` + schema file
- `apps/cards-web/src/app/(site)/companion/` — landing and connect pages
- Card model + public rendering of `exploring`

## 7. Rollout

1. Merge to `dev` after review. Persona auto-deploy is unaffected (no persona
   files change). Cards-web and cards-api still deploy by hand.
2. A human applies `0032` (expand-only; rollback SQL is in the file's header).
3. Deploy cards-api, then cards-web. The extension is useless before both.
4. Load the built extension unpacked, pair, test against dev.
5. Chrome Web Store submission is a human step (developer account, store
   listing, privacy policy URL). The extension ID is fixed by the store.

## 8. Phase 2 — the memory fact (needs a decision outside Cards)

"Inject a fact into the Memory Card" writes to the memory layer, which has
`/me/findability/declare` for a signed-in user but no service-token equivalent
(`/v1/service/*` only reviews facts that already exist). Cards-api would need
`POST /v1/service/declare {email, predicate, value}` in `services/memory`,
reusing the same `declare()` and the same card refresh. That is a change to a
service this work does not own, so it is not in this branch. Once it exists, the
rest is small: a `POST /cards/companion/facts` route that calls it, and a "Remember
this" field in the popup. Neither is built.

## 9. Not done yet / limits

- Not exercised against a real Supabase session or the production API. The
  extension is tested in real Chromium against a mock Cards API; the website's
  connect page is typechecked and built but has not been driven in a browser.
  `activeTab` itself and the right-click menu click cannot be automated.
- **Working on lines come after live memory facts.** `services/signals.py` puts
  `is_working_on` facts from a connected agent ahead of the stored list, and the
  public card shows 4. A person whose agent reports facts may not see a line they
  just typed until those facts expire (about 14 days). That rule is older than
  this work and changing it is a product call.
- Rate limiting per device is the list caps only; add a per-device limit if
  abuse shows up.
- Public rendering of `exploring` uses plain links with `rel="nofollow ugc"`;
  there is no link preview or thumbnail.
