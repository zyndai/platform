import type { Metadata } from "next";

import {
  DirectoryBrowser,
  type DirectoryPerson,
  type RankedSearch,
} from "@/components/discover/directory-browser";
import { DiscoverShell } from "@/components/discover/discover-shell";
import type { RankedRow } from "@/components/discover/ranked-results";
import { DEFAULT_LIMIT, MAX_QUERY } from "@/components/discover/search-terms";
import { cardAvatarSrc } from "@/lib/avatar";
import { CARDS_API, listCards, cardCanonicalUrl, formatMatchReason, type AgentProfileCard } from "@/lib/cards";
import { verifiedLabels, type MatchReason } from "@/lib/match-reason";
import { pageMetadata } from "@/lib/seo";

export const dynamic = "force-dynamic";

type Param = string | string[] | undefined;

interface PageProps {
  searchParams: Promise<{ q?: Param; match?: Param; limit?: Param }>;
}

const first = (value: Param): string => (Array.isArray(value) ? value[0] : value) ?? "";

export async function generateMetadata({ searchParams }: PageProps): Promise<Metadata> {
  const q = first((await searchParams).q).trim();
  const base = pageMetadata({
    title: "People Directory — Zynd",
    description: "Browse every person profile on Zynd, the AI agent discovery network.",
    path: "/directory",
  });
  // A search is a view of the directory, not a page of its own.
  return q ? { ...base, title: `${q} — People Directory — Zynd`, robots: { index: false, follow: false } } : base;
}

interface SearchResult {
  handle: string;
  agent_id: string;
  name: string;
  headline: string;
  location: string;
  skills: string[];
  availability: string;
  experience_years: number | null;
  match_reasons: MatchReason[];
  verified?: string[];
  match_score: number;
  claimed?: boolean;
}

async function searchPeople(q: string, limit: number): Promise<SearchResult[] | null> {
  try {
    // The website's own directory UI may include unclaimed cards (labelled).
    const url = `${CARDS_API}/ask?q=${encodeURIComponent(q)}&limit=${limit}&include_unclaimed=true`;
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return null;
    const data = await res.json();
    return Array.isArray(data?.results) ? data.results : null;
  } catch {
    return null;
  }
}

const SKILLS_SHOWN = 4;

function encodeSkill(name: string): string {
  return encodeURIComponent(name.toLowerCase().replace(/\s+/g, "-"));
}

function buildJsonLd(cards: AgentProfileCard[]) {
  return {
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    name: "People Directory — Zynd",
    description: "Browse every person profile on Zynd, the AI agent discovery network.",
    url: "https://cards.zynd.ai/directory",
    mainEntity: {
      "@type": "ItemList",
      name: "Zynd People Directory",
      numberOfItems: cards.length,
      itemListElement: cards.map((c, i) => ({
        "@type": "ListItem",
        position: i + 1,
        item: {
          "@type": "Person",
          name: c.identity.name,
          url: cardCanonicalUrl(c),
          description: c.citation_snippet || c.summary,
        },
      })),
    },
  };
}

function avatarOf(card: AgentProfileCard): string | undefined {
  const avatar = card.identity.avatar_url;
  return avatar && /^https?:\/\//.test(avatar) ? cardAvatarSrc({ avatar_url: avatar, handle: card.handle }) : undefined;
}

/** Only what the grid draws, so the page does not ship whole cards to the browser. */
function toPerson(card: AgentProfileCard): DirectoryPerson {
  return {
    id: card.id,
    href: card.handle ? `/p/${encodeURIComponent(card.handle)}` : `/profile/${card.id}`,
    name: card.identity.name,
    headline: card.identity.headline ?? "",
    location: card.identity.location ?? "",
    avatar: avatarOf(card),
    claimed: card.claimed !== false,
    skills: card.skills.slice(0, SKILLS_SHOWN).map((s) => ({ name: s.name, href: `/tag/${encodeSkill(s.name)}` })),
    moreSkills: Math.max(0, card.skills.length - SKILLS_SHOWN),
  };
}

export default async function DirectoryPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const q = first(params.q).slice(0, MAX_QUERY);
  const limit = Math.min(Math.max(parseInt(first(params.limit), 10) || DEFAULT_LIMIT, 1), 50);
  const wantsMatch = first(params.match) === "1" && q.trim() !== "";

  const [cards, results] = await Promise.all([listCards(), wantsMatch ? searchPeople(q.trim(), limit) : null]);

  let ranked: RankedSearch | null = null;
  if (wantsMatch) {
    // The ask API ranks people but has no photos; the directory list does.
    const photos = new Map<string, string>();
    for (const card of cards) {
      const src = card.handle ? avatarOf(card) : undefined;
      if (card.handle && src) photos.set(card.handle, src);
    }
    const rows: RankedRow[] | null = results
      ? results.map((r, i) => ({
          key: r.handle || r.agent_id,
          rank: i + 1,
          href: `/p/${r.handle || r.agent_id}`,
          name: r.name,
          headline: r.headline ?? "",
          location: r.location ?? "",
          availability: r.availability ?? "",
          years: r.experience_years ?? null,
          skills: r.skills ?? [],
          reasons: (r.match_reasons ?? []).map(formatMatchReason).filter((reason): reason is string => Boolean(reason)),
          verified: verifiedLabels(r.verified),
          claimed: r.claimed,
          score: r.match_score,
          avatar: photos.get(r.handle),
        }))
      : null;
    ranked = { query: q.trim(), limit, rows };
  }

  return (
    <DiscoverShell active="directory">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(buildJsonLd(cards)).replace(/</g, "\\u003c"),
        }}
      />
      <DirectoryBrowser
        people={cards.map(toPerson)}
        initialQuery={ranked ? ranked.query : q}
        ranked={ranked}
        intro={
          <>
            {/* div, not h1: globals.css makes every h1 uppercase gradient text */}
            <h1 className="dc-title">People on Zynd</h1>
            <p className="dc-lede">
              Profiles on Zynd, the AI agent discovery network. Each entry is one
              person, one page — skills and work synthesized from public GitHub
              activity and résumés.
            </p>
          </>
        }
      />
    </DiscoverShell>
  );
}
