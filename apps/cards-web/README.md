# cards-web

The standalone frontend for **cards.zynd.ai** — ported out of the `dashboard`
repo's `app/(site)/{p,create,profile,directory,find,search,tag,for-ai}` and
`app/agent-card` (now the `/` landing page, `app/(landing)`), per `ZYND_CARDS_MOVE_PLAN.md` phase P2. It talks to the
existing `services/cards-api` (still `api.zynd.ai`, unchanged) for card data,
and to a Supabase project for login.

## Status: live at cards.zynd.ai

The site is live and serves card reads, search, login/claim/create/edit and
the profile chat. Note the deploy caveat below.

- **Reads** — card data, search, and the memory-chat widget all go through
  `services/cards-api` (unchanged API).
- **Auth** — LinkedIn-only login (D12), backed by the aafo Supabase project
  with the `avatars` storage bucket and the LinkedIn OAuth provider enabled.
- **Deploy caveat:** as of the monorepo cutover (root `AGENTS.md` §7),
  production still serves from the old standalone `zynd-cards` checkout —
  pushing this repo does not reach the live site until the cutover lands.
  Deploy target for the cutover: Vercel, **Root Directory = `apps/cards-web`**.

## What changed from the dashboard version

- Dropped the dashboard's shared shell: `useAuth`/`Providers`/`Navbar`/root
  `layout.tsx`/`/auth/callback` were all coupled to the dashboard's own
  Prisma-backed "developer" onboarding concept, which is that product's
  business, not ours. Rewrote minimal equivalents here — same interface
  shape where callers needed it (`{ ready, authenticated, user }`), no
  Prisma, no developer lookup.
- Dropped Google, GitHub and the email magic link as login providers — cards
  login is LinkedIn only (D12 in `ZYND_DB_UNIFY_PLAN.md`, superseding the
  earlier Google+LinkedIn+magic-link decision in `ZYND_CARDS_MOVE_PLAN.md`).
  Magic link comes back once an email provider (SMTP) is chosen.
- `lib/seo.ts`, `sitemap.ts`, `llms.txt`, `llms-full.txt`, `api/indexnow` are
  rewritten to be card-only and point at `cards.zynd.ai` instead of
  `www.zynd.ai` — the dashboard's versions mixed in registry/blog content
  that doesn't belong here. `api/indexnow` uses its own IndexNow key (Bing
  requires the key file to be hosted on the exact host it's submitted for).
- Everything else — `p/[handle]/**`, the `(landing)` page, `profile/[id]`,
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

Deploy target: Vercel project on `zyndai/platform`, **Root Directory =
`apps/cards-web`** (see `ZYND_CARDS_MOVE_PLAN.md` §4 H5).
