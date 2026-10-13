# S10: understand it and test it manually

This walkthrough describes the S10 implementation in this repository. It is a
test plan, not a record of tests already run. For rollout details, see
[S10 owner home](S10_OWNER_HOME.md).

## 1. What is S10, in simple terms?

Imagine you have published your Zynd profile card. You want to know whether
people are viewing it, what information is missing, and whether anything needs
your attention. S10 gives you an **owner home at `/home`** to answer those questions.

For example, Alice opens her home and sees:

> My card is 75% complete. I can add a photo and review a suggested fact.
> My card has recorded human views and AI agent visits this week.
> I have facts waiting for approval, and an old source needs refreshing.

S10 also helps Alice:

- Edit her card with automatic saving and a visible saved state.
- Receive a weekly summary email and choose whether to receive reminder emails.
- Notice a time-sensitive fact that is about to expire.
- Choose one of her duplicate cards to keep, archive the other, and redirect its URLs.
- Make her card public or private.

The completeness score measures filled-in information. It does not measure
popularity, accuracy, or how successful the card is.

### What should you expect from other slices?

| Feature | What to expect while testing S10 today |
| --- | --- |
| Fact review | Uses the existing S02 approval flow. |
| Views and agent hits | Uses S04 events; event collection must be enabled. |
| Individual assistant connection health | Needs S09. A memory account alone does not prove an assistant is active. |
| Questions that matched the card | Needs S11 query capture. Current emitters do not populate these queries. |
| Intro request count/inbox | Needs S12. An unavailable value is expected here. |

Do not mark S10 as broken just because these future metrics show unavailable
instead of a number. Unavailable data and a known count of zero are different.

## 2. Set up the story

Use a disposable test environment and these example people:

| Person or session | Purpose |
| --- | --- |
| Alice, signed in | Owns the public card `alice-dev`. |
| Bob, a separate signed-in user | Owns a different card; checks owner isolation. |
| Incognito browser | Acts as an anonymous visitor. |
| Optional developer helper | Prepares memory facts, old sources, duplicates, and email sandbox data. |

Use your actual handles if they differ from these examples. The usual local
Cards web URL is `http://localhost:3002`; Cards API is on `http://localhost:8002`.
This is **Cards web**, not the Persona chat app.

Before making test edits, have a maintainer confirm the database target. A local
web/API process can still point to the shared production database. Shared database
migrations require human approval under [AGENTS.md](../AGENTS.md); do not apply
them just to follow this guide. See the setup appendix for required flags.

### Alice's starting card

For the numerical examples below, prepare this exact starting state:

| Information | Example | Points |
| --- | --- | --- |
| Name and headline | Alice Dev — Backend engineer | 20 |
| Summary | I build Python APIs for small teams. | 20 |
| At least one skill | Python | 15 |
| At least one social link | Alice's test GitHub profile | 10 |
| Working on or connect with | Building a developer tool | 10 |
| Photo | Missing | 0 of 10 |
| At least one project | Missing | 0 of 10 |
| At least one approved public memory fact | Missing | 0 of 5 |
| **Total** | | **75 of 100** |

A connected memory account with no approved public facts is suitable for this
starting state. Connected does not mean every suggested fact is public.

If your existing card has different data, record its starting score and test the
change in score rather than expecting exactly 75%.

## 3. Manual scenarios

### A. Alice opens her owner home

1. Sign in as Alice and open `/home`.
2. Find completeness, suggested actions, fact inbox, connection state, source
   health, recent activity, visibility, and email preferences.
3. Follow an actionable item to the editor, then return to home.
4. Open `/home` in the incognito browser.

**Expected:** Alice sees her own information and at most three suggested actions.
With the fixture above, the score is 75%. The anonymous session is taken to sign
in. A signed-in test user with no card sees a create-card action.

**Also check:** Bob's home shows Bob's information. Alice's private inbox and
owner controls are not exposed through Alice's public card.

### B. Alice improves her card

1. From home, open the editor and add a valid profile photo.
2. Wait until the editor says **Saved**.
3. Return to home and reload it.

**Expected:** The photo persists and the example score becomes **85%**. Suggested
actions update to reflect what is still missing.

Later, approving Alice's first public memory fact should bring this example to
**90%**. Further facts do not each add another five points.

**Current UI limit:** Projects and career are read-only in the editor. To test
project completeness, use a card prepared through an available onboarding/import
flow or a developer-prepared test fixture. Do not look for an add-project editor
button that is not implemented.

### C. Alice reviews suggested facts

**Prepare:** Have the developer helper create eligible, unapproved suggestions
for Alice through the existing memory flow. For example:

- Alice works with Python.
- Alice is building a developer tool.
- Alice wants to meet a technical collaborator.

These are example contents; eligibility and deduplication determine the actual
inbox count. For an exact three-item test, prepare exactly three eligible items.

1. Note the pending fact count on home.
2. Open the review inbox at `/p/alice-dev/edit#inbox`.
3. Approve one suitable fact and return to home.
4. Open Alice's public card in incognito.

**Expected:** The approved item leaves the pending queue and becomes public
through the existing review flow. Unapproved suggestions remain private. If this
is the first public fact, completeness gains five points.

**Example:** With exactly three pending items and no other activity, approving
one leaves two pending items.

### D. A visitor and an AI agent find Alice

1. Note the seven-day human-view and agent-hit counts on home.
2. In incognito, visit `/p/alice-dev` a few times.
3. Wait briefly for event collection, then reload Alice's home.
4. Optionally simulate an AI client with this read-only request:

   ```bash
   curl -sS -A 'ChatGPT-User' http://localhost:8002/cards/by-handle/alice-dev > /dev/null
   ```

5. Reload home again after the event is recorded.

**Expected:** Recorded human activity increases after visitor requests. The
simulated agent request increases agent activity when API event collection is
enabled. The window covers the last seven days.

Counts are recorded requests, not unique people. One page visit can trigger
multiple reads, so do not require exactly one increment per page opening.
Matching questions and intro requests can remain unavailable pending S11/S12.

### E. Alice's edits save automatically

1. Open `/p/alice-dev/edit` and change the headline to `Python API engineer`.
2. Stop typing and watch the save indicator.
3. After **Saved**, reload and verify the headline.
4. Change the summary to `I help small teams ship reliable Python APIs.`
5. Immediately click the editor's **Owner home** link, before waiting for autosave.
6. Return to the editor and check the summary.

**Expected:** Changes save after a short pause (about 750 ms before the save
request begins). Saved values survive reload. Internal navigation flushes pending
edits before leaving. Section indicators show the save state.

### F. A failed save does not lose Alice's draft

1. In browser DevTools, block requests matching
   `*/cards/by-handle/alice-dev/sections/*`. Keep the rest of the app online.
2. Change the headline to `My unsaved test headline` and wait for the save attempt.
3. Try the **Owner home** link.
4. Remove the request block and click **Retry saving**.
5. Wait for **Saved**, then reload.

**Expected:** The failed save shows an error/unsaved state and retains the typed
text. Internal navigation keeps Alice in the editor while saving fails. Retrying
persists the draft once the request succeeds.

**Recovery variation:** Repeat the failed save, restore network access, then
reload the same browser tab, accepting any unsaved-changes warning. The editor
offers **Restore unsaved changes** and **Discard draft**. Restore recovers the
draft for saving; discard keeps the server's saved values. This backup is local
to the session, owner, and card, rather than a promise of cross-device recovery.

### G. Two tabs do not silently overwrite each other

1. Open Alice's editor in tabs A and B before editing either tab.
2. In A, change the headline to `Backend engineer`; wait for **Saved**.
3. In the still-stale B, change the headline to `Platform engineer`.
4. Read the save result and check the persisted card in A.

**Expected:** B reports **Section changed in another session. Reload before
saving.** A's saved headline remains on the server, and B retains its draft.
Copy any desired draft text before reloading to resolve the conflict.

**Separate-section variation:** Start with two fresh tabs. Edit identity in A
and summary in B. Both should save, since they change different sections.

### H. Alice controls visibility

1. Confirm Alice's public card is visible in incognito.
2. Switch the card to private from Alice's home.
3. Reload the incognito card and `/p/alice-dev/data.json` if public JSON is enabled.
4. Check that Alice can still use her owner home and editor.
5. Restore public visibility and repeat the visitor check.

**Expected:** Private card content is unavailable through public routes and
public search. Owner access continues to work. Switching back to public restores
visitor access. Use incognito for this check so an owner session cannot mask a bug.

### I. Alice changes email preferences and previews a digest

1. Find the weekly digest and reminder-email checkboxes on home.
2. Toggle each, reload, and confirm the values persisted.
3. Click **Preview weekly digest**.
4. Compare its completeness, pending items, activity, and links with Alice's home.

**Expected:** New default preferences are weekly digest **on**, reminder emails
**off**. Changes persist and apply across the owner's cards. A failed preference
save restores the previous checkbox value and displays an error.

Previewing does not send an email or consume a weekly delivery. The preview uses
real available data, shows unavailable metrics honestly, and links to home/inbox.
The preview footer is preview-only; test unsubscribe with a real sandbox email.

### J. Alice gets a reminder before a fact expires

**Prepare:** In isolated test data, give Alice an approved public `is_seeking`
memory fact, such as `technical cofounder`, approved **five days ago in UTC**.
That predicate expires seven days after approval, so it has about two days left.
Putting “looking for a cofounder” in the normal profile text is not sufficient.

1. Have the developer helper run the configured nudge scanner without real email
   sending. A normal scan using the no-op mailer can persist in-app nudges.
2. Open home and look for the expiring-fact reminder.
3. Run the scanner again and reload home.
4. Dismiss the reminder, then scan and reload again.

**Expected:** The same fact and expiry produce one reminder rather than duplicate
rows. Dismissal remains effective for that version of the fact. A newly approved
version can receive its own reminder. An already-expired fact should not produce
this upcoming-expiry warning.

Dry-run notifications only build previews; they do not persist these nudges.
Testing actual reminder emails requires the sandbox setup in scenario L.

### K. Alice keeps one duplicate card

**Prepare:** Alice owns two disposable cards: `alice-dev` and `alice-old`.
Give them visibly different summaries. Keep the chosen canonical card public
for the redirect checks. There is no restore-archived-card UI in this flow.

1. Open home and find the duplicate-card option.
2. Choose `alice-dev` as the card to keep and complete the merge.
3. Verify `alice-dev` still has its original summary.
4. Open `/p/alice-old` in incognito.
5. Check the old handle's HTTP response, and any old short alias:

   ```bash
   curl -I http://localhost:3002/p/alice-old
   curl -I http://localhost:3002/p/alice-old/data.json
   ```

**Expected:** The old card is archived as `merged`; its URLs return **301** to
the canonical published card. The kept card's content is preserved. The old
card's contents are not automatically copied into the kept card or published.
A developer can confirm the audit snapshot in `cards.card_merges`.

Here “merge” means keep one card, archive the other, and redirect its URLs.
It does not blend two profiles into one.

**Ownership check:** Bob cannot merge Alice's card. A same-name card is not proof
of ownership. An unclaimed same-LinkedIn candidate needs the existing claim flow
before merging; do not bypass that flow by editing ownership fields.

### L. Optional: test real weekly email and unsubscribe

This needs a dedicated test deployment/database containing only test owners,
plus an SMTP provider sandbox that cannot email real owners. The notification
job scans all eligible owners in its configured database; there is no Alice-only
filter. A local server pointing at shared production data is unsuitable.

1. Have the developer helper configure the sandbox settings in the appendix.
2. Leave Alice's weekly digest on and reminder emails off for this test.
3. Run the protected owner-notifications job once, then inspect the sandbox inbox.
4. Compare the **Your week on Zynd** email with Alice's actual data and open its links.
5. Run the same job again in the same ISO week.
6. Open the unsubscribe link from the received sandbox email.
7. Before confirming, reload home and inspect the preferences.
8. Confirm unsubscribe, then reload home again.

**Expected:** Alice receives one weekly email; a second job run does not send a
second weekly email. Opening the unsubscribe link alone shows a confirmation
page and keeps preferences unchanged. Confirming turns both email preferences
off across Alice's cards and leaves her profile intact.

The sender limits weekly emails to one attempt per owner per ISO week; an
ambiguous/failed SMTP attempt is not automatically retried. Ask the developer
helper to inspect delivery results if the first email does not arrive.

To verify later suppression, check a later eligible send period using isolated
fixtures or controlled test time. Re-running immediately after unsubscribe is
not sufficient proof: weekly deduplication would also suppress that send.

## 4. Record your results

Record the deployment, date, handles, starting data, and any fixture differences.
Use **Pass**, **Fail**, or **Blocked**, with a short observation. Nothing below
has been executed merely by creating this guide.

| Scenario | Result | Observation |
| --- | --- | --- |
| A. Home and owner isolation | Not run | |
| B. Completeness changes | Not run | |
| C. Fact review | Not run | |
| D. Human and agent activity | Not run | |
| E. Autosave and navigation | Not run | |
| F. Failed save and draft recovery | Not run | |
| G. Two-tab conflict | Not run | |
| H. Visibility | Not run | |
| I. Preferences and preview | Not run | |
| J. Expiry reminder | Not run | |
| K. Duplicate merge | Not run | |
| L. Sandbox email and unsubscribe | Not run | |

For a failure, record the steps, expected result, actual result, and relevant
request status/error. Keep tokens and secrets out of screenshots and notes.

## 5. Developer setup appendix

Use [local development instructions](LOCAL_DEV.md) to set up the services.
The configured test database needs the existing migration history plus
`packages/db/cards/migrations/0010_s10_owner_home.sql` and
`0011_s10_owner_operations.sql`. This guide does not establish that those
migrations have been applied to any live environment.

Minimal relevant settings, alongside the existing auth/database/memory setup:

```dotenv
# apps/cards-web/.env.local
NEXT_PUBLIC_FEATURE_S10_HOME=true
NEXT_PUBLIC_S04_EVENTS=true
NEXT_PUBLIC_API_URL=http://localhost:8002
NEXT_PUBLIC_ZYND_API_URL=http://localhost:8001
NEXT_PUBLIC_SITE_URL=http://localhost:3002

# services/cards-api/.env
FEATURE_S10_HOME=true
SUPABASE_DB_SCHEMA=cards
FEATURE_S04_EVENTS=true
FEATURE_S10_DIGEST=false
S10_MAILER=noop
FRONTEND_URL=http://localhost:3002
SITE_BASE_URL=http://localhost:3002
API_BASE_URL=http://localhost:8002
```

Memory access requires the existing matching `MEMORY_SERVICE_TOKEN` configuration
and a working memory service. Restart services after environment changes; rebuild
Cards web when changing `NEXT_PUBLIC_*` settings for a production build.
Configure web revalidation as described in [S10 owner home](S10_OWNER_HOME.md).

For optional owner MCP reads, memory also needs `FEATURE_S10_HOME=true` and
`CARDS_API_URL=http://localhost:8002`. An authenticated client can call
`get_card_status` and `get_card_activity`; results must belong to that client's
owner. Disabled tools are not a failure of the browser scenarios above.

For scenario L only, configure `FEATURE_S10_DIGEST=true`, `S10_MAILER=smtp`, and
the sandbox provider's `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
and `SMTP_FROM` settings. Configure web/API origins reachable from the sandbox
email. The job is `POST /internal/owner-notifications`, protected by
`Authorization: Bearer <CRON_SECRET>`. Its `dry_run=true` option builds previews
without sending, claiming deliveries, or persisting nudges. Do not put secrets
in this document or run the sending job against shared production data.

### If a scenario is blocked

| Symptom | Check first |
| --- | --- |
| `/home` returns 404 | S10 web/API flags and web rebuild. |
| Home cannot load | Cards API, verified sign-in, schema setting, and approved migration status. |
| Activity does not change | S04 collection flags, user agent classification, and event collection delay. |
| Connection status is unknown | Memory service availability; unknown is different from disconnected. |
| Memory connected but no public facts | This can be correct: connection and approved facts are separate. |
| Questions or intro requests unavailable | S11/S12 dependencies; do not invent activity to hide missing data. |
| No duplicate option | Need two cards owned by the same account; unclaimed candidates need claiming. |
| No expiry reminder | Need an approved `is_seeking` fact expiring within three days and a scanner run. |
| No email | Default mailer is no-op; check sandbox settings, preferences, job result, and delivery claim. |
