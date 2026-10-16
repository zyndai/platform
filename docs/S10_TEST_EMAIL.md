# Send notification test emails

Endpoint: `POST /internal/owner-notifications/test`.

- Supply `email` to send only to that card owner.
- Omit `email` to send to **all card owners in the configured database**.
- `kind=weekly` sends the digest; `kind=reminder` sends a reminder.

Both modes require `CRON_SECRET`, bypass email preferences and delivery limits,
and leave scheduled delivery records unchanged. Requests are repeatable and not
deduplicated. Bulk mode sends once per normalized email, including owners whose
cards are private or whose preferences are off. Merged cards and unclaimed cards
without an owner email are excluded. Normal scheduled sending is unchanged.

## Setup

Configure `services/cards-api/.env` and restart Cards API:

```dotenv
S10_MAILER=smtp
SMTP_HOST=<your-provider-host>
SMTP_PORT=587
SMTP_USER=<your-provider-user>
SMTP_PASSWORD=<your-provider-password>
SMTP_FROM=<your-provider-sender>
CRON_SECRET=<your-existing-cron-secret>
SITE_BASE_URL=http://localhost:3002
API_BASE_URL=http://localhost:8002
```

SMTP must support STARTTLS. Owner home must be enabled, use the `cards` schema,
and have its migrations applied. `FEATURE_S10_DIGEST` can remain `false`: explicit
test sends bypass that flag. `S10_TEST_EMAIL` is no longer used; choose the
recipient with the request's `email` query parameter.

## Send only to yourself

Enter the existing API cron secret when prompted:

```bash
read -rsp "Cron secret: " CRON_SECRET
echo

curl --fail-with-body --max-time 120 -X POST \
  'http://localhost:8002/internal/owner-notifications/test?kind=weekly&email=your-email%40example.com' \
  -H "Authorization: Bearer ${CRON_SECRET}"
```

Replace the email with your card-owner email (`%40` is an encoded `@`; encode
`+` as `%2B` if your address contains it). A supplied empty/invalid email is
rejected; it never falls back to a bulk send. The address must match an existing
card owner, since content comes from that owner's card.

Expected response:

```json
{"sent":1,"to":"your-email@example.com","kind":"weekly","test":true}
```

## Send to all owners

This command emails every distinct card-owner address in the API's configured
database, even if that owner's preferences are off or an email was sent this week:

```bash
curl --fail-with-body --max-time 900 -X POST \
  'http://localhost:8002/internal/owner-notifications/test?kind=weekly' \
  -H "Authorization: Bearer ${CRON_SECRET}"
```

Bulk processing continues after an individual failure and returns counts plus
per-owner errors:

```json
{"sent":13,"failed":1,"kind":"weekly","test":true,"errors":[{"email":"owner@example.com","status":502,"detail":"SMTP rejected the test recipient; check sandbox recipient restrictions"}]}
```

A local API can use a production database. Check the target before choosing the
bulk command. No emails were sent when creating or testing this feature.

## Reminder tests and results

Change `kind=weekly` to `kind=reminder` in either command. The message uses current
reminder candidates, or a clearly labelled sample if there are none.

Look for **[TEST] Your week on Zynd** or **[TEST] Your Zynd card needs attention**.
SMTP success means the provider accepted the message; check spam/provider logs
if it does not arrive. After a timeout, check results before repeating: the
endpoint deliberately has no deduplication and repeating bulk mode emails all
owners again.

Tests do not change preferences, claim scheduled deliveries, or persist in-app
nudges. Test emails have no unsubscribe link because they were explicitly
requested; scheduled messages retain unsubscribe links and consent checks.

| Status | Check |
| --- | --- |
| 401 | `${CRON_SECRET}` must contain the same value configured in Cards API. |
| 404 | Owner home is disabled, or the selected email has no card. |
| 422 | Email is invalid, or `kind` is not `weekly`/`reminder`. |
| 503 | Missing SMTP settings or owner data could not be loaded. |
| 502 | SMTP authentication, sender, recipient, connection, or STARTTLS failed. |

Bulk recipient errors appear in the response's `errors` list. No frontend or
database schema change is required.
