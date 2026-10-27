# Zynd Companion

A small Chromium extension (Chrome, Edge, Brave) that updates a person's Zynd
card from the page they are on: set **Working on**, or add a repo, paper, video,
post, newsletter, blog or news article to **Currently exploring**. The plan, the
privacy rules and the reasons behind them are in
[`docs/plans/ZYND_COMPANION_PLAN.md`](../../docs/plans/ZYND_COMPANION_PLAN.md).

## How it knows the account

It does not. It is **paired** with a signed-in cards.zynd.ai session:

1. Popup → **Connect Zynd account** opens `cards.zynd.ai/companion/connect?state=…`.
2. The website signs the person in if needed, names the account, and on **Connect**
   asks cards-api for a device token (`POST /cards/companion/pair`).
3. The website hands `{state, token, profile}` to this extension's one content
   script (matched to the connect page only). The background worker keeps the token
   only if the `state` is the one it is waiting for and `GET /cards/companion/me`
   accepts it.

The token works on `/cards/companion/*` only and can be revoked from the website
or the popup. Until paired, the popup has one button.

## Develop

```bash
npm install
npm run build:dev     # dist/ → http://localhost:8002 (cards-api) and http://localhost:3002 (cards-web)
npm run build         # dist/ → api.zynd.ai and cards.zynd.ai
npm test              # unit tests (URL rules, kind detection, pairing messages)
npm run test:e2e      # real Chromium + the built extension + a mock Cards API (port 4777)
npm run typecheck
npm run package       # zynd-companion.zip for the Chrome Web Store
```

Load it: `chrome://extensions` → Developer mode → **Load unpacked** → `dist/`.
For local development run cards-api and cards-web as in
[`docs/LOCAL_DEV.md`](../../docs/LOCAL_DEV.md) with migration `cards/0032`
applied to the database they use.

## Layout

| File | Does |
|---|---|
| `src/background.ts` | Service worker: starts pairing, keeps the token, right-click menu, freshness badge |
| `src/connect-bridge.ts` | The content script on the connect page only |
| `src/popup/` | The window: Working on, Currently exploring, recent clips, Disconnect |
| `src/classify.ts` | Which links may be public, and a guess at what kind each is (pure, tested) |
| `src/api.ts` | The `/cards/companion` client; a 401 means "connect again" |
| `src/protocol.ts` | Pairing messages, mirrored in `apps/cards-web/src/lib/companion.ts` |
| `src/page-info.ts` | Run once in the current tab when the popup opens |
| `scripts/build.mjs` | esbuild + manifest; `--dev`, `--api`, `--site`, `--out` |

## Rules this code keeps

- **Click only.** Nothing reads a page until the popup is opened on it (`activeTab`).
  No `tabs`, `history`, `cookies` or `<all_urls>`; host access is the Cards API only.
- **Nothing is sent that was not shown.** The popup shows the title, kind, note and
  public link before **Add to my card**. The right-click menu only pre-fills it.
- **Private pages are refused** in `classify.ts` and again by cards-api.
- **No incognito** (`"incognito": "not_allowed"`).
- Text from pages is only ever drawn as text. `readPage()` must stay self-contained
  because Chrome serialises it into the page: do not add imports or turn on
  `keepNames`/minify in the build.

## Not yet

Memory facts (needs a `services/memory` endpoint), X bookmark import, Firefox,
a final icon (the current one is a placeholder), and a Chrome Web Store listing
(needs a developer account, a privacy policy URL and screenshots). The test
build grants broad host access to automation only; `activeTab` itself, the
right-click menu click and the toolbar icon are not exercised by the e2e tests.
