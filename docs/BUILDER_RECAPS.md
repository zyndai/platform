# Builder recaps (Auto-Brag)

Owners open **Your recaps** from `/home`, or go to `/home/recaps`. Generate a
month (`2026-10`) or quarter (`2026-Q3`), select highlights, edit the generated
caption, and download a 1200 × 630 PNG. Publish creates a public recap page;
unpublish hides both the page and its image from new requests. Previously
downloaded images or social-platform copies cannot be withdrawn by Zynd.

## Facts and privacy

- A profile project or “Working on” string has no completion timestamp and
  never counts as shipped. Owners record dated shipped/learning milestones,
  optionally using a project already on their card. These are self-reported,
  labelled as such, and private until selected in a published recap.
- Dated exploring links still present on the card may be included as
  **Explored**, never “mastered.” Historical clipped links that have already
  disappeared cannot be reconstructed. The editor states this limitation.
- GitHub uses `contributionsCollection(from:, to:)` and the exact calendar
  total for the requested period, using the existing `GITHUB_TOKEN`. This is
  a contribution count, not a commit count; visibility depends on that token.
  Missing credentials, rate limits, and upstream errors omit the count. A
  confirmed zero remains zero. See [GitHub's reference](https://docs.github.com/en/graphql/reference/users).
- Boundaries use the card's stored IANA timezone, falling back to UTC.
  Current periods say “so far”; future periods are rejected.
- Captions are generated from selected facts using a deterministic template,
  with no new AI dependency or inferred achievements. Generated copy follows
  highlight selection; manually edited copy is preserved for user review.
- Public responses contain selected highlights only, never owner emails,
  draft snapshots, or hidden highlights. They recheck current card ownership
  and published status on every request. A private, merged, deleted, or
  transferred card cannot serve an old owner's public recap.
- Published facts and captions stay frozen. Owners unpublish before editing
  or refreshing. Refresh replaces a draft's facts, selection, and caption;
  the UI requires saving local edits first.
- Links to X/LinkedIn open their sharing composers. They share a recap link
  with an OG image, rather than uploading media or posting without review.
  PNG download and copy-caption support native image posts. Existing
  `share_click` telemetry records recap share targets; links carry `ref=recap`.

## API

All owner routes reuse the existing verified Cards session and derive email
on the server; they accept no owner identifier from the browser.

| Route | Purpose |
|---|---|
| `GET /cards/mine/recaps` | Recent recap snapshots and existing project choices |
| `POST /cards/mine/milestones` | Confirm a dated shipped/learning milestone |
| `POST /cards/mine/recaps` | Generate/retrieve a period; `refresh: true` refreshes private drafts |
| `GET /cards/mine/recaps/{uuid}` | Owner-only snapshot |
| `PATCH /cards/mine/recaps/{uuid}` | Save selection/caption; `publish: true` explicitly publishes |
| `POST /cards/mine/recaps/{uuid}/unpublish` | Hide a published recap before editing |
| `GET /cards/by-handle/{handle}/recaps/{uuid}` | Selected public snapshot, only while its card is public |
| `POST /internal/recaps/generate?dry_run=true` | Inspect scheduled generation without writes |

The internal endpoint reuses `CRON_SECRET`. Without `dry_run`, it prepares
the previous complete month and quarter for published, owned cards, paginates
through the corpus, and writes one owner-home nudge per recap. Unique
card/owner/period keys prevent duplicate drafts; nudge deduplication permits
independent retries. Individual failures do not stop other owners and cause
an HTTP 503 after processing so the existing cron runner reports the failure.

`infra/single-box/crontab` runs catch-up daily at 00:15 UTC. It never posts to
social accounts or sends email. A saved snapshot is not automatically
regenerated on subsequent ticks; owners can refresh private drafts to retry
GitHub or include newly recorded historical milestones.

## Schema change and deployment

**Human approval is required before applying SQL or deploying production.**
Migration `packages/db/cards/migrations/0034_builder_recaps.sql` adds only
`cards.card_milestones` and `cards.card_recaps`, with service-role-only access,
RLS, card foreign keys, checks, and deduplication constraints. It does not
change auth providers, payments, existing tables, or environment variables.
The rollback SQL is in its header; do not run it without data-deletion approval.

1. Confirm the live Cards schema and migration history with its maintainer;
   this checkout alone does not prove which migrations are deployed.
2. Follow `packages/db/README.md` to review drift, dry-run, and explicitly
   approve/apply the Cards migration. No production SQL is applied by tests.
3. Deploy cards-api, then cards-web and the updated cron configuration.
4. Run the authenticated internal endpoint in dry-run mode, generate a test
   owner's recap, and verify preview/download/publication before normal cron.

## Validation

Run Cards API `pytest -q`, Cards web lint/typecheck/build, and
`npx playwright test tests/recaps.spec.ts` against its fixture API. The browser
tests verify hidden highlights, private draft access, PNG signature and
dimensions, public OG metadata, unpublishing, and mobile overflow.

From `packages/db`, run `npm run db:check && npm run db:lint && npm run typecheck`.
The dedicated SQL test rehearses 0034 on disposable local PostgreSQL with its
minimal parent-card dependency (no pgvector required):

```sh
CARDS_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5548/postgres \
  npx tsx --test test/cards-recaps-sql.test.ts
```

The complete migration-history rehearsal still requires pgvector as described
in `packages/db/README.md`.
