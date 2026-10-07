# Dear Agent — the new UI (example data, not wired)

Dear Agent is the new name for the card product. This folder is its complete front end, from the landing page to the
owner's screens, built from the October 2026 product review and the launch film. It runs on example data so the team
can review the experience before any backend work.

It lives in its own route group with its own root layout and stylesheet, so nothing in the live pages (`(landing)`,
`(site)`) is touched. Every route is under `/dear/…` for now.

## Run it

```bash
cd apps/cards-web
npm install
npm run dev        # then open http://127.0.0.1:3000/dear
```

No environment variables are needed for these routes.

## The idea in one rule

A person's page is a **letter to the agents**. Everything the agent learns about them is in one of three states:

| State | Meaning | Where it shows |
|---|---|---|
| pencil | found by the agent, private | the owner's inbox only |
| ink | approved by the owner | the public letter, search, the agent JSON |
| struck | never say this | nowhere, and never suggested again |

## Screens

| Route | Screen | What it replaces or adds | Guide slice |
|---|---|---|---|
| `/dear` | Landing | The current landing page. Live "ask like an agent" box, the film, the pencil/ink/struck rule | S08 |
| `/dear/write` | Write your letter | The 2,100-line create flow and its five-question quiz. Sources arrive as lines of the letter; no account until the first connection or the signature; the AI connector comes after signing | S08, S09 |
| `/dear/l/[handle]` | The public letter | The profile page. One primary action (Say hello), "true today" first, a receipt on every line, a labelled assistant, a trimmed page for unclaimed people | S03, S06, S12, S14 |
| `/dear/l/[handle]/data.json` | Agent view | `data.json`. Inked lines only, each with source and dates; 404 for unclaimed | S03, S06 |
| `/dear/home` | Your desk | The long edit form as a landing place. Who asked, what they asked, what the agent could not answer, what to do today | S04, S10 |
| `/dear/letter` | Edit my letter | Nothing equivalent today. The owner rewrites any line (double-click), adds lines to any section, strikes or restores, at any time | S02, S10 |
| `/dear/inbox` | Inbox | The review queue. Three groups with bulk actions, visible "shows as", permanent strike, and hellos in the same place | S01, S02, S05, S12 |
| `/dear/sources` | Sources | The "Add MCP" panel. One-click connect, per-assistant disconnect, last read and contribution per source | S09 |
| `/dear/share` | Share | The share menu. Short address, 320px QR with full-screen mode, per-person preview image, signature and README snippets | S07 |
| `/dear/find` | Find someone | `/directory`, `/search` and `/find` as one page that shows why each person matched | S03, S06 |
| `/dear/for-agents` | For agents | `for-ai` and the dump-style `llms.txt`. Three rules, the JSON shape, the MCP tools | S06, S11 |
| `/dear/signin` | Sign in | LinkedIn-only sign-in. Adds GitHub and Google | S08 |

Slice numbers refer to the engineering guide (`zynd-cards-eng-guide`).

## Where the data comes from

`src/lib/dear/repo.ts` is the only file the screens read from. Each function returns fixtures today and names the
service and slice it should call. To wire a screen, replace the function body; the screen does not change.

- `types.ts` — the contracts. `Fact` carries `source`, `asOf`, `state`, `approvedAt`, `expiresAt`.
- `fixtures.ts` — invented people. Dates are relative to a fixed `TODAY` so server and client render the same.
- Buttons that would write (ink, strike, accept, connect, sign) change local state only.

## What is deliberately not here

- No real sign-in, no writes, no analytics events.
- No per-person preview image route yet; `/dear/share` shows the intended design.
- The short address (`dearagent.me/<name>`) is shown as designed; no alias system exists.
- Routes are `noindex` until they replace the live pages.

## Before these replace the live pages

The UI states three things as facts. They must be true in the backend first:
1. Nothing is public without approval (S01). Today inferred facts are public on insert.
2. Inking a line updates the public letter immediately (S02).
3. "Say hello" reaches the owner and nothing is shared until they accept (S12).
