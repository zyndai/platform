# SEO & Crawlability Improvement Plan — ZyndAI Persona

**GA Measurement ID:** `G-1L9YDBKGRT`

---

## Task 1: robots.txt

**File:** `webapp/public/robots.txt`

```
User-agent: *
Allow: /
Disallow: /onboarding/
Disallow: /dashboard/
Sitemap: https://persona.zynd.ai/sitemap.xml
```

---

## Task 2: sitemap.xml

**File:** `webapp/public/sitemap.xml`

Static XML listing `/`, `/terms`, `/privacy`, `/data-deletion`, `/security`, `/contact` with `<lastmod>` and `<priority>`.

---

## Task 3: llms.txt Route Handler

**File:** `webapp/src/app/llms.txt/route.ts`

Dynamically generates Markdown-formatted list of:
- Static pages: `/`, `/terms`, `/privacy`
- Public persona pages (from backend API)
- Published pages (from backend API)

Output: `text/plain; charset=utf-8`

---

## Task 4: Google Analytics

- Install `@next/third-parties` package
- Add `<GoogleAnalytics gaId="G-1L9YDBKGRT" />` in root layout
- Add `NEXT_PUBLIC_GA_ID=G-1L9YDBKGRT` to `.env.local`

---

## Task 5: Root Metadata Enhancement

**File:** `webapp/src/app/layout.tsx`

Add to existing metadata:
- `metadataBase: new URL("https://persona.zynd.ai")`
- `robots: { index: true, follow: true }`
- `openGraph` with site_name, image, locale
- `twitter: { card: "summary_large_image" }`
- `alternates: { canonical: "/" }`
- `keywords`

---

## Task 6: JSON-LD Structured Data

**File:** `webapp/src/app/layout.tsx`

Add `WebSite` schema via `<script type="application/ld+json">` in `<head>`.

---

## Task 7: Server-Render /p/[userId] Pages

**File:** `webapp/src/app/p/[userId]/page.tsx`

Currently a client component — crawlers get an empty shell. Refactor:
- Server component: fetches persona data, generates full HTML
- Client component (`PersonaPageClient`): handles connect button, share sheet, QR code
- ISR revalidation: 60s (same as layout metadata)
- Layout's `generateMetadata()` already works — no change needed

---

## Task 8: Dependency Install

```
cd webapp && npm install @next/third-parties
```

---

## Execution Order

```
Task 8 ──→ Task 4
Task 1 ══ (parallel)
Task 2 ══ (parallel)
Task 3 ══ (parallel)
Task 5 ══ (parallel)
Task 6 ══ (parallel)
Task 7 ══ (parallel)
```
