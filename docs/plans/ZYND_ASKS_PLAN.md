# Asks — plan

| | |
|---|---|
| **Status** | Built and tested on `feat/asks`, stacked on `feat/feed` (PR #146). The migration (`cards` 0033) is rehearsed locally and **not applied anywhere**. |
| **Scope** | Cards only: `services/cards-api`, `apps/cards-web`, `packages/db/cards`. Persona, `services/memory` and `infra` are untouched. |
| **Origin** | The feed (PR #146) shows beacons as "asks" but nothing happens after one is posted. Phase 2 makes an ask reach the right people, record who offered help, close with an outcome, and leave a credit on the helper's card. |

## 1. Flow

1. **Publish.** The owner posts a beacon (existing `PUT /cards/by-handle/{handle}/beacon`). The beacon JSON gets an `id` (a UUID made in Python). After the card write succeeds, an `asks` row is inserted and any previous un-ended ask on the card is ended (`replaced`). Dismiss ends it (`dismissed`).
2. **Route.** A background task runs the existing people search (`search.search_agents`, the entry point owner suggestions use) with the ask text as the query and the asker as `searcher`. Claimed people at or above `STRONG_MATCH` (0.6, the saved-search alert threshold: "alerts email people, so they wait for a good one") are kept, minus the asker and anyone blocked, declined, revoked or hidden in either direction. The top `ASK_ROUTE_MAX` (5) go into `ask_routes`.
3. **Reach.** A routed person sees the ask in `/feed` with a boost and the reason "Asked people like you", and in the next morning digest ("Asks you could help with", at most 2). No new email type, no immediate email.
4. **Offer.** Replying to an ask item through `POST /cards/feed/reply` still sends the DM or connection request, and also records an `ask_offers` row (unique per ask and helper, so a second reply never duplicates it).
5. **Close.** The owner answers "Did your ask get answered?" on `/home`: ticks who helped (only people who offered), or "Solved another way" / "Still looking". `helped` and `solved_elsewhere` on a live ask end it (`solved`) and clear the beacon.
6. **Credit.** Chosen helpers get `credited_at`. Their public card shows a small "Helped" block. The helper's next digest says who credited them.

## 2. Tables (`cards` 0033, expand-only, RLS on, service-role only like `card_events`)

| Table | Purpose |
|---|---|
| `cards.asks` | One row per posted ask: `id` (= beacon id), `card_id` → `agent_profile_cards(id)` cascade, `owner_user_id`, `text` (1..280), `created_at`, `expires_at`, `ended_at`, `end_reason` (`dismissed`/`replaced`/`solved`), `outcome` (`helped`/`solved_elsewhere`/`still_looking`), `outcome_at`, `outcome_prompted_at`. Index `(card_id, created_at desc)`. |
| `cards.ask_offers` | Who offered help: `ask_id` cascade, `helper_user_id`, `helper_card_id` cascade, `connection_id`, `channel` (`dm`/`request`), `created_at`, `credited_at`, `credit_hidden_at`, `credit_notified_at`. Unique `(ask_id, helper_user_id)`; partial index on `helper_card_id` where `credited_at is not null`. |
| `cards.ask_routes` | Who the ask was routed to: PK `(ask_id, helper_card_id)`, `score`, `created_at`, `digest_sent_at`. Index `(helper_card_id, digest_sent_at)`. |

`agent_profile_cards.id` is `text`, so the card FKs are `text`. Every query has an index: asks by card (card index), offers by ask (unique index prefix), offers by helper (partial index), routes by helper (second index), routes by ask (PK prefix).

## 3. Consent model

- **The asker** made the ask public (a beacon is on their public card) and chooses who gets credit. The asker's own card shows nothing extra.
- **The helper** offered help through Zynd, so only people who actually messaged the asker about this ask can be credited (the API rejects any other card id with 422). The credit is public on the helper's card, so the helper can **hide** it at any time (`credit_hidden_at`), and a hidden credit disappears from the card at once.
- **Nobody is tied to an ask they never touched.** A credit also needs the asker's card to still be published.
- **Routing never reveals the asker's private data** and never emails immediately; it only adds an ask the asker already made public to someone's own feed and digest. Blocks, hides, declined and revoked connections are respected in routing, feed, digest and credits alike.
- Message text is never stored in asks tables, logs or events.

## 4. Before the migration is applied

Everything keeps working with the three tables missing. A single module (`services/asks.py`) detects "relation does not exist" / "not in the schema cache" from PostgREST, logs it once at info level, and switches the asks-only parts off for a minute at a time (so applying the migration takes effect without a restart): beacons publish and dismiss, the feed and replies work as before, and routing, offers, close-out, credits and the digest sections quietly do nothing. Publishing a beacon never fails because of asks.

## 5. Rollout and rollback

1. Merge #146, the feed fixes (#150), then this PR (rebased onto `dev`). A merge to `dev` deploys dev.cards.zynd.ai and a merge to `main` deploys prod (`.github/workflows/deploy-single-box.yml`). Neither applies migrations, and the digest and other scheduled jobs call prod only.
2. A human applies `0033` with `packages/db/README.md` step 6: drift check, then a dry run that must list `0033_asks` as the only pending cards migration, then `--yes`. It can go before or after the deploy because the code degrades without the tables. Pending migrations run in one transaction, so a failed apply changes nothing. If asks stay off more than a minute after a successful apply, reload PostgREST's schema cache (`NOTIFY pgrst, 'reload schema';`).
3. Rollback, in one transaction. cards-api need not be reverted first: with the tables gone it switches the asks features off again. Deleting the tracking row lets a later `db:migrate` apply 0033 again; `1793285560055` is 0033's `when` in `meta/_journal.json`.

```sql
BEGIN;
DROP TABLE IF EXISTS cards.ask_routes;
DROP TABLE IF EXISTS cards.ask_offers;
DROP TABLE IF EXISTS cards.asks;
DELETE FROM drizzle.__cards_migrations WHERE created_at = 1793285560055;
COMMIT;
```

Existing beacons carry no `id`; the optional `Beacon.id` is backward compatible and an ask without a row simply has no offers, routes or credit.

## 6. Test plan

- Pure selection of routes (threshold, cap, exclusions) separate from I/O; routing is idempotent.
- Tables-missing path for every asks function; a beacon publish survives an asks failure.
- Offers: idempotent, own ask refused, inactive ask ignored, event has no message text.
- Close-out: owner-only, another owner's ask id or offer id is 404, helpers must be a subset of offerers (422), `helped` needs a helper, idempotent, ends a live ask and clears the beacon, credits revalidated.
- Feed: routed boost and reason; digest: sections, escaping, `*_sent_at` set only after a successful send, dry run does not mark.
- Credits: visible only when credited, not hidden, asker still published; hide is owner-only.
- Migration: applied to a throwaway Postgres from empty, drift check, rollback SQL runs, re-apply works.

## 7. Not done

- Reminders beyond the one digest line, and a "thank you" message to helpers.
- A moderation view of credits.
- Asks for people with no card (they cannot post a beacon).

## 8. Composer

A floating **Post** button on `/feed` opens a composer (a dialog on a desktop, a bottom sheet on a phone) for posting an ask. The edit page's old beacon editor is now a short summary of the live ask plus a button that opens the same composer, so there is one way to post everywhere. **No migration**: everything below lives in the beacon JSON on the card and in the existing asks tables.

- **Kinds.** `team` (Building a team), `cofounder` (Looking for a co-founder), `hiring`, `work` (Open to work), `feedback`, `users` (Looking for early users), `investors` (Raising money), `other` (Something else). One list, `ASK_KINDS` in `services/cards-api/models/card.py`, mirrored in `apps/cards-web/src/lib/asks.ts`. A beacon with no kind (posted before kinds) reads as `other`.
- **Link.** An optional `url` on the beacon: http(s) only, at most 500 characters, a 422 on write. Rendered as its hostname with `rel="noopener noreferrer nofollow ugc"`. A stored bad kind or link reads back as null instead of breaking the card.
- **One live ask per card.** Posting replaces the live one (`replaced`, as before) and the composer says so; "Take it down" ends it (`dismissed`). Both go through the existing `save_beacon`, so the compare-and-swap (409 when the card changed), the asks row and the background routing are unchanged.
- **Limit.** `ASK_POSTS_PER_DAY` = 5 publishes per card in a rolling 24 hours, counted from the asks table (429). Skipped when the table is missing, like every other asks feature. A repost and an edit both count.
- **Endpoints.** `POST /cards/mine/ask` `{kind, text, url?}` returns `{beacon, ask_id}`; `DELETE /cards/mine/ask` returns 204; both take the card from the session. The by-handle beacon routes still work and accept `kind` and `url`. `GET /cards/mine/asks` adds `kind`, `url`, `routed` (people it was sent to, one extra query for all asks) and `offer_count`. `kind` and `url` are known only for the live ask, since the asks table does not store them.
- **Feed.** Ask items carry `content.kind` and `content.url`; `GET /cards/feed?filter=asks&kind=…` returns one kind. The reply button and the start of the message depend on the kind (`ASK_REPLY` in `lib/feed.ts`); replies still go through `POST /cards/feed/reply`, so offers are recorded. Ask items have a Report control that uses the existing report-a-card API (it says so when network controls are off). The morning digest labels each routed ask with its kind.
- **Events.** `ask_published` with `kind` and `replaced`; never the text or the link.
