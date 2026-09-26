# cards-web

The standalone frontend for **cards.zynd.ai** — ported out of the `dashboard`
repo's `app/(site)/{p,create,profile,directory,find,search,tag,for-ai}` and
`app/agent-card`, per `ZYND_CARDS_MOVE_PLAN.md` phase P2. It talks to the
existing `services/cards-api` (still `api.zynd.ai`, unchanged) for card data,
and to a Supabase project for login.

## Status: code complete, not yet live

This app builds and typechecks, but nothing is deployed or wired to
production auth yet:

- **Reads work today** — card data, search, and the memory-chat widget all
  go through the cards API exactly as they did in the dashboard, no changes
  needed there.
- **Auth does not work yet.** Login/claim/create/edit need the aafo (persona)
  Supabase project to have: the `vector` extension enabled, an `avatars`
  storage bucket, and Google/LinkedIn/email auth providers turned on — see
  `ZYND_CARDS_MOVE_PLAN.md` §4, items H2–H4 (those need your access to the
  Supabase dashboard, not something this app can do for you).
- **cards-api itself** doesn't yet trust the aafo project's tokens — that's
  phase P0 (`services/cards-api/api/auth.py`, `TRUSTED_SUPABASE_URLS`), a
  separate backend change not part of this app.
- **Card data migration** (xmfj → aafo) is phase P3, and the cutover that
  points `services/cards-api` at aafo is P4. Until then this app can read
  cards fine but a real "claim"/"create" flow has nowhere durable to land.

## What changed from the dashboard version

- Dropped the dashboard's shared shell: `useAuth`/`Providers`/`Navbar`/root
  `layout.tsx`/`/auth/callback` were all coupled to the dashboard's own
  Prisma-backed "developer" onboarding concept, which is that product's
  business, not ours. Rewrote minimal equivalents here — same interface
  shape where callers needed it (`{ ready, authenticated, user }`), no
  Prisma, no developer lookup.
- Dropped GitHub as a login provider (cards login is Google, LinkedIn, and
  email magic link per the decided plan); added the magic-link form, which
  didn't exist in the dashboard.
- `lib/seo.ts`, `sitemap.ts`, `llms.txt`, `llms-full.txt`, `api/indexnow` are
  rewritten to be card-only and point at `cards.zynd.ai` instead of
  `www.zynd.ai` — the dashboard's versions mixed in registry/blog content
  that doesn't belong here. `api/indexnow` uses its own IndexNow key (Bing
  requires the key file to be hosted on the exact host it's submitted for).
- Everything else — `p/[handle]/**`, `agent-card/**`, `profile/[id]`,
  `directory`, `find`, `search`, `tag/[skill]`, `for-ai`, `lib/cards.ts`,
  `lib/memory*.ts`, `lib/claim-tokens.ts`, `lib/supabase/*`,
  `components/memory/*`, `ProfileChatWidget`, `useMyCard` — ported with no
  logic changes beyond fixing hardcoded `www.zynd.ai` URLs to
  `cards.zynd.ai`. `globals.css` and `zynd-ui.css` are copied wholesale
  (unmodified) since several ported pages depend on exact selectors from
  them; trimming the unused parts is follow-up cleanup, not a blocker.

## Commands

```bash
npm ci
npm run dev      # dev server on 127.0.0.1
npm run build
npm run lint
```

## Env vars (Vercel)

See `.env.local.example`. In short: `NEXT_PUBLIC_SUPABASE_URL` /
`NEXT_PUBLIC_SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` point at the
**aafo** project (not xmfj), `NEXT_PUBLIC_API_URL` stays `api.zynd.ai`, and
`NEXT_PUBLIC_SITE_URL=https://cards.zynd.ai`.

Deploy target: Vercel project on `zyndai/zynd-platform`, **Root Directory =
`apps/cards-web`** (see `ZYND_CARDS_MOVE_PLAN.md` §4 H5).
