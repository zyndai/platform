# Zynd Match: warm introductions

The owner dashboard's existing People to meet section now offers **Draft an
intro**. Suggestions still come from the existing people search and two-way
matching system, including its exclusions and digest cooldowns. No new scheduled
matching job or messaging system is introduced.

## Approval flow

1. The owner sees suggested people and why their profiles fit.
2. Draft an intro loads both current, claimed, published Cards. It checks
   connection state and both owners' suggestion exclusions before producing a
   draft. It creates no connection, message, delivery claim, or email.
3. DearAgent assembles an introduction from recorded complementary needs,
   desired roles, relevant current projects, or shared skills/interests. Expired
   approved memory facts are excluded by the existing Card helpers. With the
   existing OpenRouter configuration, a model selects the strongest evidence
   IDs; it cannot invent new claims. A model failure uses the same factual
   evidence without a remote call. With insufficient evidence the UI offers an
   error rather than inventing a reason to connect.
4. The owner edits the text and explicitly chooses Send intro request. That
   action is the first approval. The send checks current exclusions again and
   calls the existing connection request service, including its limits and
   unique key per pair. An ambiguous request can be retried without creating a
   second connection. Existing pending/accepted requests are returned; closed
   requests cannot be revived.
5. The recipient sees the approved text in their Cards inbox and can accept,
   decline, or block. Only recipient acceptance opens the DM thread. The sender
   cannot accept their own request.

The morning people digest includes a review/draft link; the weekly digest lists
available matches with reasons and links to `/home#zynd-matches`. Neither sends
an introduction on the owner's behalf. Existing email preferences and delivery
limits continue to apply. No separate intro email or email address exchange is
added; the shared conversation lives in Cards.

## API

Both new routes use the existing Cards networking authentication. Browser
callers supply a signed-in Cards session, not the internal cron secret. Bound
service callers use the existing service authentication and X-Zynd-User rules.
Caller identity cannot be overridden in JSON.

- `POST /cards/network/warm-intros/draft` with `{ "target_handle": "sarah" }`
  returns `{ "target_handle", "name", "message", "reasons" }` with no-store
  caching. Drafts are not persisted until explicitly submitted.
- `POST /cards/network/warm-intros` with
  `{ "target_handle": "sarah", "message": "The reviewed introduction" }`
  returns the existing connection response `{ "connection", "existing" }`.
  Messages must contain non-whitespace text and be at most 2,000 characters.
- The existing `POST /cards/network/connections/{id}/respond` handles the
  recipient's accept/decline/block decision. Existing messaging endpoints handle
  the conversation after acceptance.

## Local verification

Open `http://localhost:3002/home`, find Zynd matches, generate a draft, edit it,
then send. Sign in as the other owner in a separate browser profile and open
`/network` to read and decide the request. Before acceptance no DM should be
available; after acceptance both people can continue in the inbox. Canceling a
draft must send nothing. Hide/not-relevant uses the existing suggestion controls.

Unit and API tests cover read-only drafting, grounded model selections and
fallbacks, expired facts, sender identity, both-direction exclusions, stale blocked
connections, edited message validation, duplicate retries and both-person
approval. Browser tests cover canceling, editing, failed send preservation, mobile
layout and recipient acceptance. Tests use fixtures and send no real emails.

No migration, new environment variable, auth changes, or feature flag is required.
Existing networking/suggestion tables and service configuration must be available
in the environment where this is deployed. Missing suggestion persistence tables
retain the existing live-compute fallback.

## Troubleshooting the draft button

Clicking opens the editor immediately with a drafting status. API errors stay
visible beside a retry action; requests that stall are aborted after 30 seconds.
If even the editor does not open, hard-refresh the dashboard to reload its
client JavaScript.

Cards networking already requires `AAFO_ISSUER` to match the shared account
project's issuer (`<Supabase project URL>/auth/v1`). A missing value rejects
networking requests even when owner home can load by email. Configure this
existing setting for the intended shared project and restart the local API;
do not remove the issuer check or accept tokens from another project. Local
authentication configuration changes require human approval under AGENTS.md.
