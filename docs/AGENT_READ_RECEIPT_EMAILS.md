# Agent read-receipt and feedback emails

Both endpoints use the existing `Authorization: Bearer <CRON_SECRET>` protection.
They do not accept arbitrary message content or new recipient addresses.

## Weekly agent digest

`POST /internal/weekly-agent-digest?dry_run=true`

Optionally add `email=<existing-owner-email>` to preview or send only to that
owner. Invalid addresses return 422; an address with no card owner returns 404.
The recipient filter preserves weekly opt-out and duplicate-send checks.

Omit `dry_run=true` to deliver to eligible published-profile owners. The sender
uses the existing SMTP setup (`S10_MAILER=smtp`, `SMTP_HOST`, `SMTP_FROM`, and
the existing SMTP credentials) and `FEATURE_S10_HOME`. Weekly delivery is always
enabled in code and does not depend on `FEATURE_S10_DIGEST`; that legacy flag
continues to control optional nudge emails. Unavailable SMTP retains the existing
no-send behavior, and weekly opt-outs and delivery limits still apply.

The dashboard's **Weekly digest** checkbox already updates
`notification_prefs.weekly_digest`. The sender checks it before claiming delivery
and again immediately before SMTP delivery. The unsubscribe link also disables it.

The email includes the last seven days' recorded AI request count, named client
breakdown (e.g. ChatGPT / OpenAI, Claude, and unidentified MCP), up to ten recent
human visitor names from the existing consent-filtered visitor view, and the five
latest redacted profile-assistant questions. Unavailable or anonymous visitor
identities are never inferred or disclosed. Client counts cover the latest 1,000
AI requests, matching the dashboard. Up to three topic phrases are derived from
the latest twenty recorded questions using the existing OpenRouter model; phrases
must occur in those questions. Without a model or on a model failure, the email
uses recorded question categories. Empty question history produces no topic section.
Questions and crawler/MCP access counts are explicitly described as separate
measurements. Topics are never described as extracted by a visiting crawler.
When the consent-filtered visitor record includes a published-profile handle,
the visitor's name and a “View profile” action link to
`https://cards.zynd.ai/p/<handle>`. The plain-text email includes the URL too.
Visitors without a returned handle are displayed without a profile link.

The HTML digest uses a responsive, 800-pixel email card with inline styling and
presentation tables. Its order is greeting, Zynd matches when available, real metrics, people who viewed,
AI client breakdown and request shares, question topics, recent questions, and
the dashboard button. People also appear before agents in the plain-text email.
No JavaScript, Tailwind CDN, placeholder metrics, or unsupported controls are used.
Matches lead both HTML and plain-text versions. The highlighted HTML section has
individual profile cards, up to two reasons per person, public-profile links,
and a review/draft button. It does not send an introduction automatically.

This endpoint and the existing `/internal/owner-notifications` job share the same
`weekly`/ISO-week delivery key, so invoking both does not duplicate the weekly
email. The existing owner-notifications workflow already runs daily and will use
the enhanced weekly template; the dedicated endpoint sends no nudge reminders.

## One-time profile feedback

`POST /internal/profile-feedback?dry_run=true`

Optionally add `email=<existing-owner-email>` to narrow the recipient. Without an
email, the endpoint scans eligible owners. Remove `dry_run=true` to deliver.
It does not create a recurring feedback schedule.

An owner must have a published profile and a first non-merged card created at
least three days earlier. Owners who disabled both weekly digests and email
nudges are skipped. Preferences and published status are checked again before
sending. Each normalized owner email gets at most one invitation, using the
existing delivery ledger with kind `profile_feedback` and period `once`.

The subject is **How’s your Zynd profile experience so far?** The message uses
the owner's first name, the supplied calendar and form links, and the existing
unsubscribe link. Its responsive HTML design matches the weekly email: Zynd
header, personal greeting, primary booking card, secondary feedback-form card,
Team Zynd sign-off, and preferences footer. It uses inline styles and presentation
tables without JavaScript or external CSS. Test-send notices appear inside the
footer only for explicit test sends; normal messages retain the unsubscribe link.

## Repeatable test sends

- `POST /internal/weekly-agent-digest/test?email=<existing-owner-email>`
- `POST /internal/profile-feedback/test?email=<existing-owner-email>`

These endpoints require `CRON_SECRET` and SMTP configuration. Weekly tests require
one explicit existing-owner email. Feedback tests accept an optional email; omit
it to send to all non-merged card owners, deduplicated by normalized email.
They **send real emails on every call**, with a `[TEST]`
subject and an explanatory test notice. They bypass email preferences, feedback
age eligibility, and weekly/lifetime delivery limits, and never claim, reset, or
update the normal delivery ledger. They do not include a live unsubscribe link.
Bulk feedback tests continue after individual failures and return sent/failed
counts and per-owner errors. Every call resends, including to opted-out owners.

For a preview without sending, use the normal endpoint with `dry_run=true`.

## Delivery safety and local validation

Dry runs return previews without SMTP calls or delivery claims. Live sends claim
the existing unique delivery key before calling SMTP. Failed or ambiguous sends
are recorded as failed and are not automatically retried, to avoid duplicate mail.
No database migration or new configuration variable is required.

Local tests cover endpoint access control, opt-out, age eligibility, normalized
owner deduplication, weekly and lifetime delivery keys, dry runs, failed sends,
grounded/redacted topics, and HTML escaping. Implementation does not deploy or
invoke either live endpoint.
