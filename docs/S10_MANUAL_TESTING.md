# S10: understand it and test it on production

This walkthrough describes the S10 implementation in this repository. It is a
test plan, not a record of tests already run. For rollout details, see
[S10 owner home](S10_OWNER_HOME.md).

Checked against local `dev` commit **`ca90e6e`** on **2026-10-15 (IST)**. Have the maintainer
confirm the deployed production commit; a local pull does not update production
or prove that feature flags and migrations are ready.

This guide uses production URLs and the behavior in that checkout. The running
production commit, flags, database migrations, and mail scheduler have not been
verified by updating this document. Keep production results as **Not run** until
you execute the relevant scenario and record evidence.

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
- See topics and saved questions people asked her public assistant, with common contact details redacted.

The pulled editor also lets Alice preview an About paragraph drafted from public
memory, inspect where public facts came from, and see tools separately from
projects. These are related editor/Memory changes covered here because you will
encounter them while testing the current owner experience.

For example, Alice approves “I use Docker” and “I'm building StudyPilot.” Her
Memory panel should put Docker under **Tools I use** and StudyPilot under
**Currently building**. Clicking **Draft from my memory** proposes an About
paragraph. Alice decides whether to use it; generating the proposal does not save
it to her card.

The completeness score measures filled-in information. It does not measure
popularity, accuracy, or how successful the card is.

### What should you expect from other slices?

| Feature | What to expect while testing S10 today |
| --- | --- |
| Fact review | Uses the existing S02 approval flow. |
| Views and agent hits | Uses S04 events; event collection must be enabled. |
| Individual assistant connection health | Owner home still says assistant details are unavailable, even with S09 implemented. A connected memory account does not prove an assistant is active. |
| Questions that matched the card | Needs S11 query capture. Current emitters do not populate these queries. |
| Chat topics | The profile assistant records categories and redacted question text in S04; home shows topics plus **Recent assistant questions**. |
| Intro request count/inbox | Available only when S12 is deployed, enabled, and its owner identity links/events are working. Otherwise it can be unavailable. The metric label still says **coming soon**, even if a count exists. |
| About drafting | Uses the Cards API's OpenRouter configuration, separately from the Cloudflare chat provider. See E1. |
| Fact origin/evidence | The editor can load owner-only fact details from Memory. Public surfaces should expose only the coarse origin, not the evidence excerpt. See C1. |
| Owner MCP status/activity | Now returned inside authenticated `get_my_context`; the separate `get_card_status` and `get_card_activity` tools have been removed. See M. |

Unavailable data and a known count of zero are different. Missing integrations
can block an individual check without blocking completeness or editor testing.
Matching-search questions and chat topics are separate kinds of activity.

## 2. Set up the story

Use designated production test accounts and cards that you own:

| Person or session | Purpose |
| --- | --- |
| Alice, signed in | Owns the public card `alice-dev`. |
| Bob, a separate signed-in user | Owns a different card; checks owner isolation. |
| Incognito browser | Acts as an anonymous visitor. |
| Optional developer helper | Confirms deployed settings and inspects approved evidence; uses isolated fixtures for scanner, archive, and mailer tests. |

| Production surface | URL used in this guide |
| --- | --- |
| Owner home | `https://cards.zynd.ai/home` |
| Alice's editor | `https://cards.zynd.ai/p/alice-dev/edit` |
| Cards API | `https://cards.api.zynd.ai` |
| Memory API / authenticated MCP | `https://api.zynd.ai` / `https://api.zynd.ai/mcp` |

Substitute your actual production test handles; `alice-dev` is an example name,
not a dev hostname. These origins match the checked-in
[single-box setup](../infra/single-box/README.md); confirm live routing first.
Its `dev.*` services also share production Supabase and Memory data.

Record the original headline, summary, photo, visibility, and email preferences
before edits, and restore reversible changes after testing. Autosave changes
the production card as soon as it succeeds. Enabling email preferences can opt
your test account into actual scheduled email delivery.

Have a maintainer confirm the settings in the appendix. Shared migrations,
production SQL, and production deployments require human approval under
[AGENTS.md](../AGENTS.md). Mark missing prerequisites as **Blocked** rather than
changing production configuration during the walkthrough.

Run **A–I**, including C1/C2, D1, and E1 where their prerequisites exist, on your
own test cards. For **J**, inspect an existing eligible
reminder by opening home; do not backdate production facts or launch the global
scanner. For **K**, inspecting and cancelling the merge dialog is sufficient
unless archival has been explicitly approved. For **L**, inspect mail already
delivered to your test account or use a sandbox; do not trigger the global sender.
**M** is an optional authenticated MCP comparison.

### Start with these production checks

1. Open `https://cards.zynd.ai/home` while signed in and record which card handle
   it shows. On accounts with multiple cards, do not assume the editor URL you
   previously used is the card selected by owner home.
2. In DevTools **Network**, enable **Preserve log**. Home's initial status read
   happens on the web server, so it need not appear as a separate browser API
   request. On a save/toggle, inspect the actual API origin, status, and response.
3. Confirm the API/web S10 settings in the appendix with the maintainer. A
   request to `https://cards.api.zynd.ai/cards/mine/status` without sign-in should
   return `401` when the S10 gate is enabled; `404` can mean the API gate is off.
   A working page or HTTP `200` by itself does not prove all dependencies work.
4. Before D/D1, recheck S04. Your earlier invalid-event POST returned `204` and
   you reported missing rows on 2026-10-14. That was evidence of a collector gate
   or deployed-version mismatch at that time, not a verified statement about
   today's configuration. A small diagnostic that cannot insert a valid event is:

   ```bash
   curl -i 'https://cards.api.zynd.ai/events' \
     -H 'Content-Type: application/json' \
     --data '{"events":[{"event":"s04_diagnostic_invalid"}]}'
   ```

   In this checkout, enabled intake returns `400` for that unknown event; a
   disabled flag/schema gate returns `204` before validating the name. A `400`
   verifies that validation ran, not that valid events persist. Continue with
   D's actual card reads and count/storage evidence. For `404`, `503`, or a
   different response, record the body and deployed route/configuration.

If collection is still gated or writes fail, mark activity/chat counts
**Blocked by S04** and continue with home, editor, completeness, and preferences.

### Alice's starting card

The numerical examples below use this starting state. On production, record your
existing score instead of removing real information to force the fixture:

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

**Score limit:** Completeness currently checks stored fields, including whether
the stored Memory array is nonempty. It does not filter expired facts or score
the public derived signal lists. A score increase proves a filled-in field, not
that all public facts are current or accurate.

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

If S12 is enabled for Alice, home can also show her intro inbox. Compare it with
her `/intros` view using existing requests. Intro creation and decisions are
covered by [S12 manual testing](S12_MANUAL_TESTING.md), not a requirement to pass S10.

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

**Prepare:** Use eligible pending suggestions already belonging to Alice's test
Memory account. Approve only facts she actually wants public. Examples:

- Alice works with Python.
- Alice is building a developer tool.
- Alice wants to meet a technical collaborator.

These are example contents; eligibility and deduplication determine the actual
inbox count. If there are no eligible items, record this branch as Blocked.

1. Note the pending fact count on home.
2. Open the review inbox at `/p/alice-dev/edit#inbox`.
3. Approve one suitable fact and return to home.
4. Open Alice's public card in incognito.

**Expected:** The approved item leaves the pending queue and becomes public
through the existing review flow. Unapproved suggestions remain private. If this
is the first public fact, completeness gains five points.

**Example:** With exactly three pending items and no other activity, approving
one leaves two pending items.

Publish one item at a time and watch both the review queue and the editor's
**ZYND Memory** panel. The updated review flow awaits the returned snapshot (or
a refresh when no snapshot is returned), so the published item should appear
without requiring a full page reload. Inspect `POST /cards/mcp/approve` and its
`zynd_memory` result if the queue changes but the panel does not. A failed
snapshot refresh can leave stale content even after the approval succeeded.

### C1. Alice can explain the facts on her card

1. In the editor's **ZYND Memory** panel, compare the printed fact count with
   the groups shown. Tools, current work, and ventures should have separate groups
   such as **Tools I use**, **Working on**, and **Currently building**.
2. If there are more than six displayed facts, click **Show all N**, count the
   items, then click **Show fewer**.
3. Inspect an existing fact with provenance. Examples include **Reported by your
   coding agent**, **From your profile import**, or **You added this**.
4. When recorded evidence exists, inspect its **Because: “…”** excerpt.
5. Compare with the public card and `data.json` in incognito. Use a fact whose
   evidence has extra harmless wording, so the excerpt is distinguishable from
   the approved fact itself.

**Expected:** The printed count matches the deduplicated list accessible through
Show all. Initially the panel shows up to six items across groups. The owner-only
`GET /cards/mcp/card-facts` supplies provenance/evidence details; an evidence
excerpt is limited to 160 characters. Facts with no recorded evidence should
not acquire an invented **Because** sentence.

Public content can show the approved fact and coarse origin. The owner-only
evidence excerpt must not be added to public page/JSON responses. Bob must not
receive Alice's owner details through his session. Use the helper's isolated
ownership tests for deliberate forged requests; never share account tokens.

If detail loading fails, the panel still renders snapshot facts and any origin
already stored there. Record missing evidence as an unavailable integration,
rather than expecting every historical fact to have a source sentence. The
panel reflects the stored snapshot; use S06's public-view check separately for
expiry and public fact parity.

### C2. Public signals follow approved memory without changing stored edits

Use existing live facts of type `is_working_on` and `has_expertise_in`, or approve
suitable real suggestions on your test account. A project (`is_building`) and a
tool (`uses_tool`) do not populate these two signal lists by themselves.

1. Note the editor's saved **Working on** values and inspect its owner read,
   `GET /cards/mine`, if needed. This is the stored card used for editing.
2. Fetch the public card JSON, replacing the handle:

   ```bash
   curl -sS 'https://cards.api.zynd.ai/cards/by-handle/alice-dev' \
     | python3 -m json.tool
   ```

3. Inspect `working_on` and `can_help_with`, then compare with the public page.
4. Make a normal unrelated editor change, wait for **Saved**, and confirm derived
   items have not been copied into the editor's stored lists.

**Expected:** Public `working_on` puts live work-stream facts first, newest
approval first, then stored entries, capped at four when such facts exist.
`can_help_with` puts live expertise first by confidence, then stored entries,
capped at six when such facts exist. Both merges deduplicate ignoring case.
Without eligible live facts, the stored lists are returned unchanged.

The editor intentionally loads stored values. Deleting a stored entry does not
revoke an independently approved Memory fact; removing the Memory fact does not
delete an independently stored entry. If the same text has both origins, it may
remain public until both are removed. Test removals only on expendable facts you
intend to remove, or in isolation. Existing expired `is_working_on` facts should
stop contributing after 14 days; do not backdate production rows to force this.

### D. A visitor and an AI agent find Alice

1. Note the seven-day human-view and agent-hit counts on home.
2. In incognito, visit `/p/alice-dev` once to check normal page access.
3. Make these direct API reads one at a time, using Alice's actual handle:

   ```bash
   curl -sS -o /dev/null -w '%{http_code}\n' -A 'Mozilla/5.0 Chrome/120.0' https://cards.api.zynd.ai/cards/by-handle/alice-dev
   curl -sS -o /dev/null -w '%{http_code}\n' -A 'ChatGPT-User' https://cards.api.zynd.ai/cards/by-handle/alice-dev
   ```

4. Check for `200` responses, wait a few seconds for background event writes,
   then reload home. Use event evidence to confirm attribution if counts differ.

**Expected:** When API collection is enabled and storage succeeds, the first
direct read emits a human `view` and increases Human views; the second emits an
AI-classified `view` and increases Agent hits. The window is the last seven days.
S10 Agent hits adds AI-classified `view` and `agent_fetch` events for Alice's handle.

Counts are recorded requests, not unique people. One page visit can trigger
multiple reads, so do not require exactly one increment per page opening.
Browser page reads can happen on the web server without forwarding the visitor's
User-Agent and be classified `unknown`, so the incognito visit alone need not
raise Human views. Directory-wide `llms.txt` and `/ask` events lack Alice's handle;
they do not automatically raise her owner metrics. Public-MCP events also normally
classify as `unknown` with the current wrapper.

**If collection is disabled:** Home should show dashes and **Activity measurement
is unavailable**, rather than pretending no one visited. A `200` fetch does not
prove an event was stored. See [S04 manual testing](S04_MANUAL_TESTING.md).

### D1. Visitors ask Alice's assistant questions

With S04 collection and the production chat provider already enabled:

1. In incognito, ask Alice's public card **Can I book a call?**.
2. In another fresh chat session, ask **What do they build?**.
3. Wait briefly, then reload Alice's home.
4. Compare **What people asked the assistant** with its starting counts.

**Expected:** Recorded questions add to **Contact** and **Work** respectively.
Events now contain category/character count and redacted question text for newly
admitted questions. Home shows the latest 20 saved questions from the last seven
days as well as category totals, without visitor identities or assistant replies.
Earlier question text cannot be recovered. A seeded welcome
demo answer does not count as a real chat request. Requests refused by the chat
filter or limiter do not generate these events; an admitted request can be
counted even if answer streaming later fails.

If chat/provider or S04 prerequisites are missing, mark D1 Blocked and continue
with the editor tests. Empty chat topics do not establish zero activity while
event collection itself is unavailable.

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

### E1. Alice previews an About paragraph before choosing to save it

**Prepare:** Alice has live public Memory in at least one supported section:
building, working on, expertise, learning, or tools. The API has a working
`OPENROUTER_API_KEY` and configured `OPENROUTER_MODEL`. This provider is separate
from the public chat provider. If unavailable, mark generation Blocked; ordinary
manual About editing can still pass.

1. Record the saved About paragraph. In the editor's **About** section, click
   **Draft from my memory** once.
2. Inspect `POST /cards/mine/summary-draft`. On success, read **Proposed summary**
   and **Based on**. Confirm the editable About text and public card are unchanged.
3. Click **Keep mine**; the proposal disappears and the original text remains.
4. Wait at least 15 seconds after the previous generation request, then draft
   again. Read it before clicking **Use this draft** on your test card.
5. Wait for **Saved**, reload, and compare the About text and public card.
6. Restore the original paragraph if this was only a temporary test.

**Expected:** Draft generation returns `{draft, based_on}` and saves nothing.
Keep mine discards only the proposal. Use this draft puts it into the About
field, which S10's normal summary autosave then persists. The model does not
automatically replace the owner's text.

The prompt uses supported live public facts (up to six per section), card
identity/headline, and selected current role data. Private suggestions and
owner-only evidence excerpts are excluded. Check that the proposal is grounded
in that information; output filtering does not prove every model claim is true.

With no supported live facts, the endpoint returns `422` with **Nothing approved
in your memory yet to base a summary on**. Another attempt inside the 15-second
per-owner cooldown can return `429`. Provider errors or rejected output return
`502` with **Couldn't draft a summary this time, try again**. A failed draft
request must retain the saved paragraph and any manual draft. Observe ordinary
errors; use isolated mocks for deliberate provider failure/cooldown testing.

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
Perform this only on your designated test card and restore its original
visibility. Note the HTTP status/body if an agent preview still exposes content.

### I. Alice changes email preferences and previews a digest

1. Find the weekly digest and reminder-email checkboxes on home.
2. Record original values. Toggle each only on your designated test account,
   reload, confirm persistence, then restore the original preferences.
3. Click **Preview weekly digest**.
4. Compare its completeness, pending items, activity, and links with Alice's home.

**Expected:** Defaults for cards without stored preferences are weekly digest
**on**, reminder emails **off**; existing users may have different choices.
Changes persist and apply across the owner's cards. A failed preference
save restores the previous checkbox value and displays an error.

Previewing does not send an email or consume a weekly delivery. The preview uses
real available data, shows unavailable metrics honestly, and links to home/inbox.
The preview footer is preview-only; test unsubscribe with a real sandbox email.
The current digest includes completeness, fact inbox, and human/agent activity.
S12 can add pending-intro information and a review link when available. Chat-topic
counts are on home; the current digest does not include that topic breakdown.

### J. Alice gets a reminder before a fact expires

**Prepare:** On production, use an existing approved public `is_seeking` fact
on Alice's test card, such as `technical cofounder`, approved **five days ago in UTC**.
That predicate expires seven days after approval, so it has about two days left.
Putting “looking for a cofounder” in the normal profile text is not sufficient.
If no fact expires within three days, mark this check Blocked; backdating fixtures
belongs in an isolated environment.

1. Open home and look for the expiring-fact reminder.
2. Reload home again; the owner status read itself persists eligible in-app nudges.
3. On the test account, dismiss that reminder, then reload again.

**Expected:** The same fact and expiry produce one reminder rather than duplicate
rows. Dismissal remains effective for that version of the fact. A newly approved
version can receive its own reminder. An already-expired fact should not produce
this upcoming-expiry warning.

Opening home does not itself send an email. Do not launch
`/internal/owner-notifications` to test this on prod: it scans all owners and may
send real mail. Its `dry_run=true` mode previews but does not persist these
nudges; it still scans all owners. Testing scanner/email behavior belongs to L.

### K. Alice keeps one duplicate card

**Production default:** If Alice already has duplicate test cards, open the
**Merge cards** dialog, inspect **Keep this card**, then choose **Cancel**.
Cancellation should archive nothing. Missing duplicates make this branch Blocked.

**Archive execution: Not run on prod unless explicitly approved.** This operation
changes durable rows and redirects; there is no restore-archived-card UI. Use
isolated duplicate fixtures for the full test below, or approved expendable
production test cards. Do not archive a real profile just to exercise the feature.

**Prepare:** Alice owns two disposable cards: `alice-dev` and `alice-old`.
Give them visibly different summaries. Keep the chosen canonical card public
for the redirect checks. There is no restore-archived-card UI in this flow.

1. Open home and find the duplicate-card option.
2. Choose `alice-dev` as the card to keep and complete the merge.
3. Verify `alice-dev` still has its original summary.
4. Open `/p/alice-old` in incognito.
5. Check the old handle's HTTP response, and any old short alias. These URLs are
   for an explicitly approved production merge; use the isolated site's origin
   instead when testing sandbox fixtures:

   ```bash
   curl -I https://cards.zynd.ai/p/alice-old
   curl -I https://cards.zynd.ai/p/alice-old/data.json
   ```

**Expected:** The old card is archived as `merged`; its URLs return **301** to
the canonical published card. The kept card's content is preserved. The old
card's contents are not automatically copied into the kept card or published.
A developer can confirm the audit snapshot in `cards.card_merges`.
Production SQL inspection requires the approval described in AGENTS.md.

Here “merge” means keep one card, archive the other, and redirect its URLs.
It does not blend two profiles into one.

**Ownership check:** Bob cannot merge Alice's card. A same-name card is not proof
of ownership. An unclaimed same-LinkedIn candidate needs the existing claim flow
before merging; do not bypass that flow by editing ownership fields.

### L. Optional: inspect a delivered weekly email and unsubscribe

**Production approach:** Inspect a weekly email already delivered to Alice's
designated test inbox. Compare its data with home and check its home/review links.
If no email exists or sending is disabled, mark delivery Blocked rather than
triggering the global job. Defaults are `FEATURE_S10_DIGEST=false` and a no-op
mailer, so saving email preferences alone does not prove delivery is enabled.

Open that test email's unsubscribe link and confirm that a confirmation page
appears without changing preferences. Only confirm unsubscribe if you intend
to disable both email options for that test owner; verify the result in home.
The production site origins should be `cards.zynd.ai` for home and
`cards.api.zynd.ai` for the unsubscribe endpoint. The generic Memory host routes
legacy `/cards/*` paths too, so compare actual configured URLs with the deployment.

**Repeated job execution, delivery deduplication, and SMTP failure checks are
Not run on prod by default.** Ask the maintainer for existing scheduler/delivery
evidence. The checked-in workflow schedules a scan at **08:00 IST**; a schedule
on a non-default branch does not prove it runs. See the sandbox procedure below.

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

### M. Optional: Alice reads owner status through her assistant

Use Alice's existing authenticated Memory MCP connection at
`https://api.zynd.ai/mcp`. The anonymous public Cards MCP endpoint does not return
owner-home details. Confirm the Memory S10 flag and Cards bridge settings in the
appendix first; no service secret belongs in a client prompt.

1. Refresh the client's tool list after its server is updated. Call
   **`get_my_context`** with its default arguments using Alice's connection.
2. Inspect `status` and `activity` in the returned object. Compare the handle,
   completeness, pending review count, and available seven-day activity with
   Alice's home, allowing for new requests between reads.
3. If a separate Bob test connection exists, repeat and confirm it returns Bob's
   data. Do not pass Alice's email/uid as a tool argument.

**Expected:** The current MCP exposes one self-context read tool.
`get_my_context.status` contains the owner status, and `.activity` is a metrics
object, not an array. `get_card_status`, `get_card_activity`, and `get_my_card`
are removed tools; the public approved facts are now in `get_my_context.card`.
The packet's `facts`, `profile`, and `brief` are private context, not public-card
data. Keep the full packet out of shared screenshots.

With `cards:read` or legacy `user` scope, the owner keys are present: either
real data or null when disabled/unavailable/no card exists. Without those read
scopes, both keys are omitted; `cards:approve` alone does not grant this read.
Null, an omitted key, and a known zero count have different meanings. Do not
grant broader scopes during this walkthrough just to make a test pass.

The status bridge uses one protected service request to Cards API. Owner home
reads can persist eligible reminders, while this MCP status read uses the
nonpersisting path. Per-assistant connection details on home remain unavailable
even when this read succeeds.

## 4. Record your results

Record the deployment, date, handles, starting data, and any fixture differences.
Use **Pass**, **Fail**, **Blocked**, or **Not run on prod**, with a short observation.
Record activity and chat topics separately within D. Nothing below
has been executed merely by creating this guide.

| Scenario | Result | Observation |
| --- | --- | --- |
| A. Home and owner isolation | Not run | |
| B. Completeness changes | Not run | |
| C. Fact review | Not run | |
| C1. Memory grouping/counts/origin/evidence | Not run | Existing facts; evidence stays owner-only. |
| C2. Derived public signals | Not run | Public lists can differ from stored editor values. |
| D. Human/agent activity | Not run | Recheck current S04 collection/persistence. |
| D1. Assistant chat topics | Not run | S04 and chat provider required. |
| E. Autosave and navigation | Not run | |
| E1. About draft preview/acceptance | Not run | OpenRouter and supported live public facts required. |
| F. Failed save and draft recovery | Not run | |
| G. Two-tab conflict | Not run | |
| H. Visibility | Not run | |
| I. Preferences and preview | Not run | |
| J. Expiry reminder | Not run | Existing eligible facts only on prod; no global scanner. |
| K. Duplicate merge | Not run | Dialog/cancel on prod; archive requires separate approval. |
| L. Email and unsubscribe | Not run | Existing test email on prod; global sender checks deferred. |
| M. Owner MCP context/status/activity | Not run | Optional; current tool is `get_my_context`. |

For a failure, record the steps, expected result, actual result, and relevant
request status/error. Keep tokens and secrets out of screenshots and notes.

## 5. Production prerequisites and developer appendix

Have the maintainer verify the existing production configuration. The Cards
database needs the preceding migration history plus
`packages/db/cards/migrations/0010_s10_owner_home.sql` and
`0011_s10_owner_operations.sql`. This guide does not establish that those
migrations have been applied to any live environment.

Expected home/activity prerequisites, alongside the existing auth/database/memory
setup. These are values to confirm, not instructions to edit production env files:

```dotenv
# Deployed cards-web build
NEXT_PUBLIC_FEATURE_S10_HOME=true
NEXT_PUBLIC_S04_EVENTS=true
NEXT_PUBLIC_API_URL=https://cards.api.zynd.ai
NEXT_PUBLIC_ZYND_API_URL=https://api.zynd.ai
NEXT_PUBLIC_SITE_URL=https://cards.zynd.ai

# Running cards-api configuration
FEATURE_S10_HOME=true
SUPABASE_DB_SCHEMA=cards
FEATURE_S04_EVENTS=true
MAINTENANCE_READONLY=false
FRONTEND_URL=https://cards.zynd.ai
SITE_BASE_URL=https://cards.zynd.ai
API_BASE_URL=https://cards.api.zynd.ai
```

### Where the production configuration is loaded

For the checked-in single-box setup, have the maintainer verify these locations
on the actual deployment. Other hosting arrangements may load them differently.

| Process | Configuration source | What to verify |
| --- | --- | --- |
| Cards API (`cards` compose service) | `services/cards-api/.env.prod`, loaded by `infra/api-box/docker-compose.prod.yml` | API flags/schema, origins, Memory bridge, and optional provider settings. |
| Cards web (`cards-web` PM2 app) | `apps/cards-web/.env.local` at build time | Web flags, Cards/Memory public origins, and shared revalidation secret. |
| Memory API/MCP/worker | `services/memory/.env.prod`, loaded into the corresponding compose services | Matching service token, optional S10 MCP reads, and optional agent-path snapshot sync. |

These API files use dotenv syntax such as `FEATURE_S10_HOME=true`, not a YAML
`FEATURE_S10_HOME: True` line. If your deployment supplies environment through
YAML instead, the value must reach the running process as an environment value.
Updating a file in this checkout does not confirm the live process received it.
Have the maintainer use the approved deployment process for any required reload.

Memory access requires `MEMORY_LAYER_URL` to reach the correct Memory service,
the existing matching `MEMORY_SERVICE_TOKEN`, and a working Memory connection.
Web flags are baked into the deployed build.
Missing flags or migration prerequisites are Blocked findings; a production
restart/rebuild or schema change requires the maintainer's approval/process.
The API now defaults `WEB_REVALIDATE_URL` to
`https://cards.zynd.ai/api/revalidate` when unset; the secret still needs to match
web's `WEB_REVALIDATE_SECRET`. An explicit URL override must reach that deployed
web app. Confirm revalidation if saved edits or visibility changes do not reach
public previews; an unset secret makes the notification a no-op.

### Optional dependencies for the new checks

| Scenario | Existing configuration/data to confirm |
| --- | --- |
| C1 fact origin/evidence | Cards-to-Memory service bridge and the deployed owner-card-facts endpoint; old facts may have no evidence. |
| C2 public signals | Eligible live public `is_working_on`/`has_expertise_in` snapshot facts. No new dedicated signal feature flag exists here. |
| D/D1 activity | API `FEATURE_S04_EVENTS=true`, `SUPABASE_DB_SCHEMA=cards`, successful event inserts. Web `NEXT_PUBLIC_S04_EVENTS=true` enables its emitters; direct API events use the API flag. |
| D1 public chat | Existing `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_AI_KEY`. |
| E1 About proposal | Existing `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`, plus supported live public facts. There is no separate About-draft feature flag. |
| M owner MCP | Memory `FEATURE_S10_HOME=true`, `CARDS_API_URL` reaching Cards API, matching service token, and an existing token with read scope. |

For M, a public origin can be `CARDS_API_URL=https://cards.api.zynd.ai`; the
compose-network origin can be `http://cards:8000` where reachable. Do not use
`http://localhost:8002` inside a Memory container unless deployment networking
actually routes that address to Cards API. `CARDS_API_BASE_URL` is a separate
setting used by the public MCP wrapper; changing it alone does not configure
the owner status bridge.

The pulled Memory code also supports best-effort snapshot refresh after
agent-path fact mutations. It requires `FEATURE_S02_CARD_SYNC=true`, a working
`CARDS_API_URL`, and matching `MEMORY_SERVICE_TOKEN` in the process performing
the mutation. This is optional when testing the normal web Publish flow.
If you intentionally approve/forget an expendable fact through an assistant,
verify the public snapshot separately: the async notification can fail even
when the Memory mutation succeeded. Do not launch the global refresh job to
force a production result.

### Sandbox-only sender and regression checks

Use [local development instructions](LOCAL_DEV.md) for an isolated checkout and
database. The following sender settings are for scenario L's **sandbox only**.
Never switch production to a no-op adapter or run its global sender as a test.

Configure `FEATURE_S10_DIGEST=true`, `S10_MAILER=smtp`, and
the sandbox provider's `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
and `SMTP_FROM` settings. Configure web/API origins reachable from the sandbox
email. The job is `POST /internal/owner-notifications`, protected by
`Authorization: Bearer <CRON_SECRET>`. Its `dry_run=true` option builds previews
without sending, claiming deliveries, or persisting nudges. Do not put secrets
in this document or run the sending job against shared production data.

Existing mocked developer checks can be run outside the production service
environment with production credentials removed:

```bash
cd services/cards-api
SUPABASE_DB_SCHEMA=cards .venv/bin/python -m pytest -q \
  tests/test_owner_home.py tests/test_s04_events.py tests/test_chat_s14.py \
  tests/test_summary_draft.py tests/test_signals.py tests/test_mcp_connector.py
```

These cover completeness, owner isolation, unavailable activity, chat categories,
save conflicts, reminder deduplication, no-op delivery, unsubscribe behavior,
About preview/no-save behavior, derived signals, and owner fact details.
They do not establish that production flags, event writes, migrations, SMTP, or
cache revalidation are working. Run the full suite in the same isolated setup
before/after changes and compare failures; legacy-schema mocks can fail when
the whole suite is forced to `cards`.

In Memory's separate isolated test environment, the consolidated owner MCP
checks include:

```bash
cd services/memory
uv run pytest -q tests/test_context_packet.py tests/test_s09.py \
  tests/test_card_sync.py tests/test_card_provenance.py
```

The mocked Cards web checks use the local fixture API/auth server, not production:

```bash
cd apps/cards-web
npm run test:e2e -- tests/owner-home.spec.ts tests/owner-memory.spec.ts \
  tests/owner-about-draft.spec.ts tests/memory-sections.spec.ts
```

Use a disposable checkout without production env files, install the documented
Playwright browser dependencies, and ensure no other server is running on the
fixture ports. The config can reuse a local web server, so verify its mocked API
settings before trusting the results. Browser fixture tests do not prove live
sign-in, provider output, or production email delivery.

### If a scenario is blocked

| Symptom | Check first |
| --- | --- |
| `/home` returns 404 | Deployed S10 web flag, API flag/schema gate, and built web bundle; do not rebuild prod without approval. |
| Home cannot load | Cards API, verified sign-in, schema setting, and approved migration status. |
| Activity does not change | S04 flag/schema gate, event storage, handle/actor classification, and write delay. An HTTP `200` alone does not prove an event was written. |
| Incognito visits do not raise Human views | Server-side card reads may be classified `unknown`; use scenario D's direct browser-classified API request. |
| No chat topics | Chat/provider and S04 availability, admitted messages, and category metadata; seeded demo answers do not count. |
| Connection status is unknown | Memory service availability; unknown is different from disconnected. |
| Memory connected but no public facts | This can be correct: connection and approved facts are separate. |
| Publish removes the queue item but the Memory panel stays stale | Approve response snapshot, follow-up refresh, account mapping, and cache revalidation; inspect C's request evidence. |
| Memory count is larger than the visible list | Click Show all; count the deduplicated items. Missing Show all/items is a C1 finding. |
| No Because excerpt | Historical evidence may be absent or the owner-only details fetch failed; no invented sentence is expected. |
| Public Working on differs from editor | C2 intentionally merges live Memory into public reads, while `/cards/mine` loads stored editable values. |
| About proposal fails | Supported live facts; `422` for none, `429` for cooldown, `502` for provider/rejected output. Cloudflare chat working does not prove OpenRouter works. |
| About changed without choosing Use this draft | Check summary section save requests and report a preview/no-save failure; generation must not silently replace saved text. |
| Assistant cannot find get_card_status/get_card_activity | Those tools were removed; refresh discovery and use `get_my_context.status`/`.activity`. |
| MCP status/activity omitted or null | Omitted means no owner read scope; null means authorized but unavailable/disabled/no card. Check the Memory S10 flag and `CARDS_API_URL`. |
| Matching questions unavailable | Current `/ask` and public-MCP emitters omit full query text; this is separate from chat-topic counts. |
| Intro requests unavailable | Deployed S12 flags, owner identity links, Persona availability, and S04 projection; use S12's own guide. |
| No duplicate option | Need two cards owned by the same account; unclaimed candidates need claiming. |
| No expiry reminder | Need an approved `is_seeking` fact expiring within three days; refreshing owner home can persist the reminder without a scanner run. |
| No email | Maintainer confirms digest flag, SMTP adapter, preferences, scheduler, and delivery claim; do not trigger the global job on prod. |
