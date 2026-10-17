# S12 manual testing: Alice and Bob

S12 lets Bob ask to connect with Alice after finding her card. Alice decides
whether to accept and whether to arrange a call. A request does not book a
meeting or share private information automatically.

This guide tests the human request/decision flow. AI assistants may read their
owner's intro inbox with permission; Cards-native networking is covered by the
Cards network UI and authenticated Cards MCP tools.
For setup and implementation details, see [S12 intros](S12_INTROS.md).

## Prepare the example

Use a disposable test deployment, not a local process connected to production.
The new migrations, feature flags, service credentials, and shared identity
links must be ready first. Shared database changes require human approval.

| Person | Example setup |
| --- | --- |
| Alice | Claimed, public card `alice-dev`, active Persona, linked Memory account. |
| Bob | Signed in with the same shared Supabase project; active Persona and linked Memory account. His own card is optional. |
| Cara | Separate account for checking unauthorized access and limits. |
| Incognito visitor | Signed out. |

Cards web usually runs at `http://localhost:3002`, Persona web at
`http://localhost:3000`. Substitute your test deployment URLs and actual handles.
Use separate browser profiles for Alice and Bob.

Example request:

> I’m building a developer tool and would like your advice about its Python API.
> Would you be open to a short call?

The system gets Bob's identity from his account. He does not type another
person's id or email into the request form.

## A. Bob sends a request

1. Sign in as Bob and open Alice's card.
2. Click **Request intro**.
3. Enter the example reason. Check **I would also like to arrange a call**.
4. Click **Send intro request**.
5. Follow **View your sent requests**.

**Expected:** Bob sees a pending request. He cannot approve his own request.
Alice sees the same pending request on Cards `/home` or `/intros`, and in
Persona `/dashboard/intros`. Opening the normal Persona inbox also provides a
link to the intro inbox.

No call is booked, and private-profile/account access is not granted.

## B. Alice accepts the intro without allowing a call

1. Open Alice's received requests.
2. Leave **Allow coordinating a call** unchecked.
3. Click **Accept intro**.
4. Refresh Bob's sent requests and Alice's Persona intro inbox.

**Expected:** All views show accepted after refresh. They can continue the
conversation in Persona. The intro UI offers no call proposal for this request.
The interface says that no meeting has been booked.

## C. Alice approves a call and suggests a time

Use another test requester/persona pair for this scenario. An existing
connection is not reset to create a second intro between the same pair.

1. Send an intro that asks for a call.
2. As Alice, check **Allow coordinating a call**, then accept.
3. Choose a future time under **Propose a 20-minute call (your local time)**.
4. Click **Propose time**.
5. Open the conversation in Persona and inspect the meeting proposal.

**Expected:** There is one proposed meeting ticket. The other participant can
review it through Persona's existing meeting flow. The selected time is converted
to a timestamp with a timezone; a proposed ticket is not a scheduled booking.

**Variation:** Alice can enter the optional time while accepting the intro.
Acceptance and the proposal should succeed together, without duplicate tickets
when the same operation is retried.

Booking onto calendars uses the existing calendar setup and confirmations. This
release proposes the chosen time; it does not automatically find mutual free slots.

## D. Alice declines or blocks

Use separate fresh test pairs for each branch:

1. Decline one pending request.
2. Block another requester from a pending request.
3. Refresh the requester and owner inboxes.
4. Try another request from the blocked requester to another eligible card
   owned by Alice, if the fixture includes one.

**Expected:** Declined requests create no accepted connection or meeting.
Blocking also creates a deny rule. The blocked requester cannot submit a new
intro to Alice through another card.

Cards and Persona show the same decision after refresh. A later conflicting
accept/decline attempt returns a conflict rather than overwriting the decision.

## E. The owner chooses who can request intros

1. In Persona `/dashboard/intros`, add a known requester to the allow list.
2. Open **Who can request an intro?** and inspect the rules.
3. Try a request from a different fresh test account.
4. Remove the allow-list rule and repeat with a fresh eligible pair.

**Expected:** While the allow list has entries, only listed people may request
intros. A listed person's request still needs owner approval. Removing the last
allow-list entry restores normal eligibility; deny rules remain effective.

Existing pair connections still prevent duplicate intros, even after rule removal.

## F. Signed-out, unclaimed, private, or unlinked cases

| Case | Expected result |
| --- | --- |
| Incognito opens an eligible claimed card | Intro form asks the visitor to sign in before sending. |
| Visitor opens an unclaimed card | No intro action; a direct create request is refused too. |
| Card is private | Public profile and intro intake are unavailable. |
| Owner has no active linked Persona | No intro action. |
| Owner has a missing/conflicting Memory link | No intro action; no guessing by email or name. |
| Bob lacks an active Persona or Memory link | Clear refusal; no completed intro is created. |
| Bob uses a legacy project's token or an MCP token | Human intro endpoint refuses it. |
| Alice tries an intro to herself | Request is refused. |
| Cara tries to read or decide Alice's request | No access to Alice's inbox or decision. |

Some negative cases need a developer to prepare isolated fixtures or make direct
API requests. Do not change ownership fields or disable auth to simulate them.

## G. A failed send preserves Bob's request

1. Use DevTools to temporarily block the intro POST request, or have a developer
   simulate a Persona service outage in the test deployment.
2. Fill the form and submit.
3. Confirm the error appears and the reason stays in the form.
4. Restore the request path and retry without changing the reason or asks.

**Expected:** The retry uses the same submission key. Even if the first attempt
reached Persona before its response was lost, there is one intro, one connection,
and one request event. The UI only confirms success after a successful response.

Draft recovery here covers a retry in the current form. S10's editor draft
restoration is a separate feature; do not assume this intro form has that backup.

## H. Two owner tabs decide at the same time

1. Open the same pending request in two Alice tabs.
2. Accept in one and decline in the other as closely together as possible.
3. Refresh both views.

**Expected:** One final decision wins. The conflicting operation is refused.
It cannot leave an accepted thread with a declined intro or create two proposals.
Retrying the same successful decision does not repeat its side effects.

## I. Limits, activity, and digest links

1. Have a developer set low daily limits in the disposable environment.
2. Send requests across fresh requester/owner pairs until each limit is reached.
3. Inspect the next response and Alice's inbox.
4. With S04 enabled, compare the seven-day intro count on S10 home before and
   after a successful request. Refresh as needed for reconciliation.
5. Preview Alice's weekly digest and follow its intro-review link.

**Expected:** Requests over a limit return a clear refusal and do not create a
connection. Denied/rate-limited attempts are audited. Limits reset on UTC day
boundaries, not the browser's local midnight.

Successful request/acceptance events are recorded once despite retries or later
refreshes. Digest links open authenticated review; visiting a link alone does not
approve a request. Missing upstream intro data shows unavailable instead of zero.
Digest preview does not send email.

## J. Permissions cannot be bypassed

With a developer using isolated test accounts:

1. As Bob, attempt to accept Alice's request or enable her connection permissions.
2. Attempt direct Supabase changes to thread status/permissions and meeting decisions.
3. Try sending another message or proposing a meeting on a pending S12 thread.
4. After Alice approves a call, have her revoke meeting permission and try a new proposal.

**Expected:** Unauthorized changes are refused at API and database boundaries.
Pending requests cannot bypass approval through another messaging/meeting path.
Revocation blocks a later proposal. Full-profile and account-posting permissions
remain outside the intro grant.

## K. Optional: an assistant reads the owner's inbox

1. Connect an owner assistant through S09 with the `cards:read` scope.
2. Enable the read-only S12 MCP integration in the test deployment.
3. Call `list_intros` and compare it with that owner's received requests.
4. Try the same tool from an assistant without `cards:read`.

**Expected:** Authorized reads show only that owner's data. The unscoped assistant
cannot use the tool. Intro initiation remains a human Cards flow.

## Record results

These manual scenarios have not been executed merely by creating the guide.

| Scenario | Result | Notes |
| --- | --- | --- |
| A. Send and receive | Not run | |
| B. Accept without call permission | Not run | |
| C. Call proposal | Not run | |
| D. Decline/block | Not run | |
| E. Allow/deny preferences | Not run | |
| F. Eligibility and identity | Not run | |
| G. Failure and retry | Not run | |
| H. Concurrent decisions | Not run | |
| I. Limits/activity/digest | Not run | |
| J. Permission boundaries | Not run | |
| K. Owner MCP read | Not run | |

Record the deployment, handles, expected result, actual result, and request status
for failures. Keep tokens and real private user data out of screenshots and notes.
