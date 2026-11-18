# Builder recaps (Auto-Brag)

Owners open **Your recaps** from `/home`, or go to `/home/recaps`. Generate a
month (`2026-10`) or quarter (`2026-Q3`), select highlights, edit the generated
caption, and download a 1200 × 630 PNG. Publish creates a public recap page;
unpublish hides both the page and its image from new requests. Previously
downloaded images or social-platform copies cannot be withdrawn by Zynd.

## Facts and privacy

- New public GitHub repositories are imported from the profile linked on the
  card. The scan uses `created_at` within the recap's exact calendar period;
  recent pushes to old repositories and later visibility changes do not count
  as new creation. Owned public forks may appear too; the label is **New public
  repository**, never an inferred shipped project. Private repositories are
  excluded even when the existing token can read them.
- Repository lists are requested in creation-descending order, up to five pages
  of 100, stopping at older creation dates. Partial results, outages, and missing
  profile links are distinguished in the editor. A 20-second overall timeout
  bounds the scan. REST public imports work without a token; `GITHUB_TOKEN`
  increases rate limits. No new settings, scopes, or migrations are required.
- Dated manual shipped/learning milestones remain optional and private until
  selected in a published recap. Exact duplicate evidence URLs are shown once.
  Previously imported repositories from the same profile/period survive a
  failed or partial refresh, while a complete scan replaces its old evidence.
- Contribution totals still use `contributionsCollection(from:, to:)` with the
  existing `GITHUB_TOKEN`. Missing credentials or upstream errors omit the
  count; an observed zero stays zero. Contributions are not a commit count.
- New drafts combine new public repositories, contribution totals, and manual
  milestones. Release, merged-PR, and browser-exploring imports have been removed.
  Refresh a private draft to replace older imported sources; published snapshot
  data remains unchanged until the owner unpublishes and refreshes it.
- The generated caption is a short first-person paragraph summarizing selected
  repositories, contributions, shipped projects, and learning milestones. It
  includes at most two names per category plus a remainder count. The editor,
  shared page, and PNG show the paragraph (long custom PNG text is excerpted).
  Owners may edit it. Generated paragraphs follow selection changes; custom
  captions stay under the owner's control.
- Caption writing uses the existing OpenRouter client/model/key. It starts
  with “Hi connections,”, names the recap period, shares progress naturally,
  and ends with a friendly invitation to connect. The model writes the opening
  and closing around a verified factual sentence.
  The prompt receives only the period and whether it is in progress, never
  project names, counts, owner email, or hidden highlights. Facts are inserted
  verbatim, and model framing is checked for unsupported claims. Malformed,
  unsupported, timed-out, or unavailable responses fall
  back to an editable factual greeting. The model timeout is 15 seconds with
  no retries. The editor identifies fallback copy and allows another attempt.
- **Rewrite with AI** saves the current selection and replaces only the
  caption, without fetching GitHub again. Caption generation metadata is
  owner-only and stripped from public snapshots, since old draft copy may
  refer to a highlight the owner subsequently hid. Published recaps require
  unpublishing before rewriting. No new environment settings or migrations.
- Boundaries use the card's stored IANA timezone, falling back to UTC.
  Current periods say “so far”; future periods are rejected.
- Captions are generated from selected facts with a deterministic fallback.
  Saving changed selections regenerates automatic copy; manually edited copy
  is preserved for user review.
- Public responses contain selected highlights only, never owner emails,
  draft snapshots, or hidden highlights. They recheck current card ownership
  and published status on every request. A private, merged, deleted, or
  transferred card cannot serve an old owner's public recap.
- Published facts and captions stay frozen. Owners unpublish before editing
  or refreshing. Refresh replaces a draft's facts, selection, and caption;
  the UI requires saving local edits first. Generate now also refreshes existing
  private drafts so new GitHub activity and recently recorded milestones appear
  without a separate refresh step. The owner API's default remains retrieve-only
  unless `refresh: true` is sent; cron does not regenerate existing snapshots.
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
| `POST /cards/mine/recaps/{uuid}/caption` | Rewrite a private draft's caption with AI from supplied `selected_ids`; save selection and copy |
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
