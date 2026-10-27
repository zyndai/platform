import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { headers } from "next/headers";
import { after } from "next/server";
import { BadgeCheck, Calendar, Clock, Globe, Search, Sparkles, Video } from "lucide-react";

import {
  fetchCardByHandle,
  fetchCardView,
  fetchGithubExtras,
  cardCanonicalUrl,
  featureS06CardView,
  getMyCard,
  type AgentProfileCard,
  type CardFact,
  type CardView,
  type ContributionStats,
  type Project,
} from "@/lib/cards";
import { createClient } from "@/lib/supabase/server";
import { imgProxyUrl } from "@/lib/avatar";
import { pageMetadata } from "@/lib/seo";
import { SkillMatrix } from "./skill-matrix";
import { withShareRef } from "@/lib/attr";
import { ShareQrGroup, CopyPermalinkIcon } from "./share-controls";
import type { ResumeData } from "./resume-pdf";
import { EditCardButton } from "./edit-card-button";
import { ProfileSignIn, ClaimCardButton, ProfileAccountChip } from "./profile-auth-actions";
import { CountUp } from "./count-up";
import { AutoScroll } from "./auto-scroll";
import { ContributionHeatmap } from "./contribution-heatmap";
import { ProfileView } from "@/components/ProfileView";
import { logAgentFetch } from "@/lib/track";
import { parseSearchRef } from "@/lib/search-link";
import { ProfileChatWidget } from "@/components/ProfileChatWidget";
import { FallbackAvatar } from "@/components/FallbackAvatar";
import { WorkExperienceCard } from "./work-experience-card";
import { HeroAskPanel } from "./hero-agent-bar";
import { ProjectsCard } from "./projects-card";
import { WorkGallery } from "./work-gallery";
import { MemoryCard } from "./memory-card";
import { ClaimBanner } from "./claim-banner";
import { ConnectionButton } from "@/components/network/ConnectionButton";
import { memoryFactFamily, memoryFactKey } from "@/lib/memory-facts";
import { readEdition } from "@/lib/editions";
import { EditionHero } from "./edition-banner";
import { EditionSignals } from "./edition-signals";
import { cleanTopic, publicTopics } from "@/lib/profile-quality";
import { BeaconCard } from "@/components/BeaconCard";
import { BookingAvailability } from "@/components/BookingAvailability";

interface PageProps {
  params: Promise<{ handle: string }>;
  searchParams: Promise<{ preview?: string; sid?: string; r?: string }>;
}

/* ─── utils ─────────────────────────────────────────────────────────────── */

function isBlank(s: string | null | undefined): boolean {
  if (!s) return true;
  const low = s.toLowerCase().trim();
  return low === "" || low === "n/a" || low === "not specified" || low === "unknown" || low === "none";
}

function safeUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const { protocol } = new URL(url);
    return protocol === "http:" || protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}

function compact(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(n);
}

function githubAvatar(url: string | null | undefined, size = 400): string | null {
  const safe = safeUrl(url);
  if (!safe) return null;
  try {
    const { hostname, pathname } = new URL(safe);
    if (!/(^|\.)github\.com$/i.test(hostname)) return null;
    const [user, ...rest] = pathname.split("/").filter(Boolean);
    if (!user || rest.length > 0) return null;
    return `https://github.com/${encodeURIComponent(user)}.png?size=${size}`;
  } catch {
    return null;
  }
}

function usernameFromUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  return url.replace(/\/+$/, "").split("/").pop() || null;
}

function displayExcerpt(raw: string | null | undefined): string {
  if (!raw) return "";
  const stripped = raw.replace(/<[^>]*>/g, " ");
  const decoded = stripped
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCharCode(parseInt(n, 16)));
  return decoded
    .replace(/https?:\/\/t\.co\/\S+/gi, "")
    .replace(/[ \t]+/g, " ")
    .replace(/ ?\n ?/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

const VSCROLL_VISIBLE = 3;
const VSCROLL_SECS_PER_ROW = 3.5;
const POST_ROW_H = 128;
const POST_GAP = 12;

const POST_STYLES = [
  { card: "bg-[#111827] text-white border-slate-700", badge: "bg-white/10 text-white", text: "text-slate-200", meta: "text-slate-400", link: "pf-post-link-0" },
  { card: "bg-[#e0e7ff] border-indigo-200", badge: "bg-[#3b82f6] text-white", text: "text-[#1e293b]", meta: "text-indigo-600", link: "pf-post-link-1" },
  { card: "bg-[#111827] text-white border-slate-700", badge: "bg-white/10 text-white", text: "text-slate-200", meta: "text-slate-400", link: "pf-post-link-2" },
];

/** Badge text for posts from a newsletter or blog; X and LinkedIn have their own glyph. */
const POST_PLATFORM_LABEL: Record<string, string> = { substack: "Substack", medium: "Medium", blog: "Blog" };

const OBSESSION_CARDS: {
  key: "connect_with" | "love_talking_about" | "working_on";
  label: string;
  card: string;
  chip: string;
  unit: string;
}[] = [
  { key: "love_talking_about", label: "Love Talking About", unit: "TOPICS", card: "bg-[#bbf7d0] border border-[#86efac] text-[#064e3b]", chip: "bg-white text-[#064e3b]" },
  { key: "working_on", label: "Working On", unit: "TRACKS", card: "bg-[#fef08a] border border-[#fde047] text-[#78350f]", chip: "bg-white text-[#78350f]" },
  { key: "connect_with", label: "Connect With", unit: "PEOPLE", card: "bg-[#c7d2fe] border border-[#818cf8] text-[#1e1b4b]", chip: "bg-white text-[#312e81]" },
];

/* ─── brand glyphs ──────────────────────────────────────────────────────── */

function GithubGlyph({ size = 16 }: { size?: number }) {
  return (
    <svg className="fill-current" style={{ width: size, height: size }} viewBox="0 0 24 24" aria-hidden>
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
    </svg>
  );
}

function XGlyph({ size = 14 }: { size?: number }) {
  return (
    <svg className="fill-current" style={{ width: size, height: size }} viewBox="0 0 24 24" aria-hidden>
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  );
}

function LinkedinGlyph({ size = 16 }: { size?: number }) {
  return (
    <svg className="fill-current" style={{ width: size, height: size }} viewBox="0 0 24 24" aria-hidden>
      <path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z" />
    </svg>
  );
}

const LINK_LABELS: Record<string, string> = {
  github: "GitHub", x: "X", twitter: "X", linkedin: "LinkedIn",
  website: "Website", portfolio: "Portfolio", linktree: "Linktree",
};

function LinkGlyph({ platform, size = 15 }: { platform: string; size?: number }) {
  const key = platform.toLowerCase();
  if (key === "github") return <GithubGlyph size={size} />;
  if (key === "x" || key === "twitter") return <XGlyph size={size - 1} />;
  if (key === "linkedin") return <LinkedinGlyph size={size} />;
  return <Globe style={{ width: size, height: size }} strokeWidth={2} aria-hidden />;
}

function linkLabel(platform: string) {
  return LINK_LABELS[platform.toLowerCase()] ?? platform.charAt(0).toUpperCase() + platform.slice(1);
}

const GRADIENTS = [
  "linear-gradient(135deg, #3B82F6, #1D4ED8)",
  "linear-gradient(135deg, #10B981, #047857)",
  "linear-gradient(135deg, #8B5CF6, #6D28D9)",
  "linear-gradient(135deg, #EC4899, #BE185D)",
  "linear-gradient(135deg, #F59E0B, #B45309)",
];
function getGradient(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return GRADIENTS[Math.abs(hash) % GRADIENTS.length];
}

function getHashNumber(str: string, min: number, max: number): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
  return min + (Math.abs(hash) % (max - min + 1));
}

const LEVEL_META: Record<string, { label: string; color: string; bar: string; glow: string; bars: number }> = {
  expert: { label: "Expert", color: "#D97706", bar: "#F59E0B", glow: "rgba(245,158,11,.4)", bars: 3 },
  advanced: { label: "Advanced", color: "#5448D4", bar: "#7B72E9", glow: "rgba(123,114,233,.35)", bars: 2 },
  intermediate: { label: "Mid", color: "#0284C7", bar: "#0EA5E9", glow: "rgba(14,165,233,.35)", bars: 1 },
  beginner: { label: "Beginner", color: "#059669", bar: "#10B981", glow: "rgba(16,185,129,.35)", bars: 1 },
};
const levelMeta = (l: string) => LEVEL_META[l.toLowerCase()] ?? LEVEL_META.intermediate;

const SKILL_ACCENTS: Record<string, string> = {
  rust: "#F97316", "c++": "#0070BA", cuda: "#5C9400", python: "#0284C7", kubernetes: "#6366F1",
  pytorch: "#E11D48", terraform: "#9333EA", go: "#14B8A6", "distributed systems": "#0891B2",
  "performance testing": "#059669",
};
const skillAccent = (name: string) => SKILL_ACCENTS[name.trim().toLowerCase()] ?? "#7B72E9";

/* ─── view model ──────────────────────────────────────────────────────────── */

function buildView(card: AgentProfileCard) {
  const { identity } = card;

  const links = Object.entries(identity.links ?? {})
    .map(([platform, url]) => [platform, safeUrl(url)] as const)
    .filter((e): e is readonly [string, string] => e[1] !== null);

  const projects: (Project & { stars: number | null; tech: string[] })[] = card.projects.map((p) => ({
    ...p,
    stars: p.stars ?? null,
    tech: p.tech ?? [],
  }));

  const skillKeywords = new Set(card.skills.map((s) => s.name.toLowerCase()));
  const writing = card.writing_samples
    .map((s) => ({ ...s, excerpt: displayExcerpt(s.excerpt), metrics: s.metrics ?? [] }))
    .filter((s) => s.excerpt.length > 0)
    .sort((a, b) => {
      const score = (text: string) => {
        const t = text.toLowerCase();
        let n = 0;
        for (const kw of skillKeywords) if (t.includes(kw)) n++;
        return n;
      };
      return score(b.excerpt) - score(a.excerpt);
    });

  const endorsementQuote = card.endorsement?.quote ?? (isBlank(card.citation_snippet) ? null : card.citation_snippet);

  const xQuote =
    writing.find((s) => ["x", "twitter"].includes(s.platform.toLowerCase()))?.excerpt ??
    writing[0]?.excerpt ??
    endorsementQuote ??
    (isBlank(card.summary) ? null : card.summary);

  const linkedinPosts = writing
    .filter((s) => s.platform.toLowerCase() === "linkedin")
    .map((s) => s.excerpt);
  const xPosts = writing
    .filter((s) => ["x", "twitter"].includes(s.platform.toLowerCase()))
    .map((s) => s.excerpt);

  const linkedinScrollItems = linkedinPosts.length > 0 ? linkedinPosts : endorsementQuote ? [endorsementQuote] : [];
  const xScrollItems = xPosts.length > 0 ? xPosts : xQuote ? [xQuote] : [];

  return {
    links,
    projects,
    writing,
    endorsementQuote,
    xQuote,
    linkedinScrollItems,
    xScrollItems,
    linkedin: {
      connections: card.linkedin_stats?.connections ?? null,
      posts: card.linkedin_stats?.posts ?? null,
    },
    github: {
      repos: card.github_stats?.total_repos ?? null,
      activeRepos: card.github_stats?.active_repos ?? null,
      topLanguages: card.github_stats?.top_languages ?? [],
      commits: card.github_stats?.total_commits ?? null,
      followers: card.github_stats?.followers ?? null,
    },
    x: {
      handle:
        card.x_stats?.handle ??
        (identity.links?.x ? `@${usernameFromUrl(identity.links.x)}` : null),
      followers: card.x_stats?.followers ?? null,
      posts: card.x_stats?.posts ?? null,
      impressions: card.x_stats?.impressions ?? null,
    },
    contributions: card.contribution_stats ?? null,
  };
}

/* ─── SEO ───────────────────────────────────────────────────────────────── */

function buildJsonLd(card: AgentProfileCard, view?: CardView | null) {
  const identity = view?.identity ?? card.identity;
  const sameAs = Object.values(identity.links || {})
    .filter((v): v is string => Boolean(v))
    .filter((v) => /^https?:\/\//.test(v));
  const image = /^https?:\/\//.test(identity.avatar_url || "") ? identity.avatar_url : undefined;
  const facts = (view?.facts ?? []) as CardFact[];
  const knowsAbout = publicTopics(view?.skills ?? card.skills, facts);
  const worksFor = facts
    .filter((f) => f.type === "is_affiliated_with" && f.text)
    .map((f) => ({ "@type": "Organization", name: f.text }));
  const jobTitle = identity.headline || facts.find((f) => f.type === "is_affiliated_with")?.text;
  const url = view?.cite_as || cardCanonicalUrl(card);
  return {
    "@context": "https://schema.org",
    "@type": "ProfilePage",
    dateCreated: card.created_at,
    dateModified: view?.fresh_as_of || card.updated_at,
    mainEntity: {
      "@type": "Person",
      name: identity.name,
      description: card.citation_snippet || view?.summary || card.summary,
      image,
      sameAs,
      knowsAbout,
      ...(jobTitle ? { jobTitle, hasOccupation: { "@type": "Occupation", name: jobTitle } } : {}),
      ...(worksFor.length ? { worksFor } : {}),
      ...(identity.location ? { address: { "@type": "PostalAddress", addressLocality: identity.location } } : {}),
    },
    breadcrumb: {
      "@type": "BreadcrumbList",
      itemListElement: [
        { "@type": "ListItem", position: 1, name: "Zynd", item: "https://cards.zynd.ai" },
        { "@type": "ListItem", position: 2, name: "Directory", item: "https://cards.zynd.ai/directory" },
        { "@type": "ListItem", position: 3, name: identity.name, item: url },
      ],
    },
  };
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { handle } = await params;
  const card = await fetchCardByHandle(handle);
  if (!card) {
    return pageMetadata({
      title: "Profile not found",
      description: "This profile does not exist on Zynd.",
      path: `/p/${handle}`,
    });
  }
  const name = card.identity.name || "Profile";
  const headline = card.identity.headline;
  const canonical = cardCanonicalUrl(card);
  const claimed = card.claimed === true;
  return {
    ...pageMetadata({
      title: headline ? `${name} — ${headline} — Zynd` : `${name} — Zynd`,
      description: card.citation_snippet || card.summary,
      path: `/p/${handle}`,
    }),
    ...(claimed ? {} : { robots: { index: false, follow: true } }),
    alternates: { canonical },
    openGraph: {
      type: "profile",
      url: canonical,
      title: headline ? `${name} — ${headline}` : name,
      description: card.citation_snippet || card.summary,
      // Per-card OG image comes from ./opengraph-image.tsx (file convention) —
      // no generic image here.
      ...(card.identity.links.github ? { username: handle } : {}),
    },
    twitter: {
      card: "summary_large_image",
      title: headline ? `${name} — ${headline} — Zynd` : `${name} — Zynd`,
      description: card.citation_snippet || card.summary,
    },
  };
}

/* ─── page ──────────────────────────────────────────────────────────────── */

export default async function PersonPage({ params, searchParams }: PageProps) {
  const { handle } = await params;
  const query = await searchParams;
  const visitorPreview = query.preview === "visitor";
  const fromSearch = parseSearchRef(query.sid, query.r);
  const card = await fetchCardByHandle(handle);
  const cardView = featureS06CardView() && card ? await fetchCardView(handle) : null;
  if (!card) {
    // Self-heal stale "my profile" links: a visitor who is signed in and
    // owns a card lands on their current handle instead of a dead 404
    // (handles can be renamed, and old links/cookies can point at a handle
    // that no longer resolves). The lookup itself is best-effort — a failure
    // falls through to the 404 below.
    let mineHandle: string | null = null;
    try {
      const supabase = await createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (session?.access_token) {
        const mine = await getMyCard(session.access_token);
        mineHandle = mine?.handle ?? null;
      }
    } catch {
      // auth/mine lookup failed — fall through to the 404
    }
    // Outside the try so redirect()'s control-flow throw isn't swallowed.
    if (mineHandle && mineHandle !== handle) {
      redirect(`/p/${encodeURIComponent(mineHandle)}`);
    }
    notFound();
  }
  // Found through a previous (renamed) handle — point the URL at the
  // canonical one so links, sharing and SEO settle on a single address.
  if (card.handle && card.handle !== handle) {
    redirect(`/p/${encodeURIComponent(card.handle)}`);
  }

  // Crawlers may read HTML without mounting ProfileView. Preserve their header
  // at this boundary; our backend fetches otherwise identify only the web server.
  // Human view counts still come from ProfileView (agent_fetch is separate).
  const requestHeaders = await headers();
  if (!requestHeaders.has("next-router-prefetch") && requestHeaders.get("purpose") !== "prefetch") {
    const userAgent = requestHeaders.get("user-agent");
    after(() => logAgentFetch("profile-page", userAgent, handle));
  }

  const { identity } = card;
  const claimed = card.claimed === true;
  const edition = readEdition(identity.edition);
  const v = buildView(card);
  const canonical = cardCanonicalUrl(card);
  // Shown and copied without the scheme; this is where the card actually lives
  // (cards.zynd.ai), and the /profile/<id> form when it has no handle.
  const permalink = canonical.replace(/^https?:\/\//, "");

  const initials = (identity.name || "?")
    .split(/\s+/).map((p) => p[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();

  const nameParts = (identity.name || "").trim().split(/\s+/);
  const nameLines = nameParts.length > 1
    ? [nameParts.slice(0, -1).join(" "), nameParts[nameParts.length - 1]]
    : nameParts;

  const rawAvatar = safeUrl(identity.avatar_url);
  const ghAvatar = githubAvatar(identity.links?.github);
  const avatarUrl = rawAvatar ?? ghAvatar;
  const heroAvatarSrc = imgProxyUrl(rawAvatar, ghAvatar, card.handle || handle);
  const linkedinLinked = !!identity.links?.linkedin;
  const skills = card.skills.filter(s => cleanTopic(s.name)).sort((a, b) => b.evidence_count - a.evidence_count);

  /* Résumé-relevant slice of the card, handed to the Export / Share menu.
     Unclaimed cards get no résumé export: nothing but the owner should be
     able to turn a scraped profile into a document. */
  const resumeData: ResumeData | null = claimed
    ? {
        name: identity.name || card.handle || card.id,
        headline: isBlank(identity.headline) ? null : identity.headline,
        location: isBlank(identity.location) ? null : identity.location,
        summary: isBlank(card.summary) ? null : card.summary,
        experienceYears: card.experience_years,
        profileUrl: canonical,
        links: v.links.map(([platform, url]) => ({ platform, url })),
        skills: skills.map((s) => ({ name: s.name, level: s.level })),
        work: (card.work_experience ?? []).filter((j) => !!(j.title || j.company)),
        projects: v.projects.map((p) => ({
          name: p.name,
          description: p.description,
          url: p.url,
          tech: p.tech,
          stars: p.stars,
        })),
      }
    : null;

  const syncedAt = (() => {
    const d = new Date(card.updated_at);
    return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString("en-US", { month: "short", year: "numeric" }).toUpperCase();
  })();

  const obsessionSources: Record<(typeof OBSESSION_CARDS)[number]["key"], string[]> = {
    connect_with: card.connect_with,
    love_talking_about: card.love_talking_about,
    working_on: card.working_on,
  };
  const obsessions = OBSESSION_CARDS.filter((row) => obsessionSources[row.key].length > 0).map((row) => ({
    ...row,
    items: obsessionSources[row.key],
  }));

  const linkedinHandle = usernameFromUrl(identity.links?.linkedin);
  const linkedinUrl = safeUrl(identity.links?.linkedin);
  const githubHandle = usernameFromUrl(identity.links?.github) || card.handle || "profile";
  const githubUrl = safeUrl(identity.links?.github);
  const ghLogin = usernameFromUrl(identity.links?.github);
  const cardHasGithub = !!(identity.links?.github || card.github_stats || card.contribution_stats);
  const ghExtras = cardHasGithub && ghLogin ? await fetchGithubExtras(ghLogin) : null;
  const xUrl = safeUrl(identity.links?.x);
  const bookingLinks = [
    { label: "Calendly", url: safeUrl(card.calendly_url) },
    { label: "Google Calendar", url: safeUrl(card.google_calendar_url) },
  ].filter((l): l is { label: string; url: string } => !!l.url);

  const MEMORY_GROUPS: Record<string, { label: string; icon: string }> = {
    is_founder_of: { label: "Founded", icon: "🏢" },
    has_experience_in: { label: "Experience", icon: "📋" },
    is_building: { label: "Currently building", icon: "⚙️" },
    is_working_on: { label: "Working on", icon: "⚙️" },
    is_learning: { label: "Learning", icon: "📚" },
    is_seeking: { label: "Seeking", icon: "🤝" },
    open_to: { label: "Open to", icon: "🤝" },
    has_expertise_in: { label: "Expert in", icon: "🧠" },
    uses_tool: { label: "Tools I use", icon: "🧰" },
    is_affiliated_with: { label: "Works at", icon: "🏢" },
    is_located_in: { label: "Based in", icon: "📍" },
  };
  const GROUP_ORDER = ["is_founder_of", "has_experience_in", "is_building", "is_working_on", "is_learning", "is_seeking", "open_to", "has_expertise_in", "uses_tool", "is_affiliated_with", "is_located_in"];
  const ENUM_LABELS: Record<string, string> = {
    co_founder: "a co-founder", technical_feedback: "technical feedback",
    early_users: "early users", mentoring: "mentoring", being_mentored: "being mentored",
    peer_review: "peer reviews", collaboration: "collaboration", investment: "investment",
    community: "community", coffee_chat: "coffee chats", mentoring_others: "mentoring others",
    early_user_testing: "early user testing",
  };
  const HALF_LIFE_DAYS: Record<string, number> = {
    is_seeking: 7,
    is_working_on: 14,
    is_building: 60,
    uses_tool: 365,
  };

  // Server request timestamp for expiry filtering (not client render purity).
  // eslint-disable-next-line react-hooks/purity -- RSC request-scoped clock
  const nowMs = Date.now();
  const memoryGroups = (() => {
    type MemItem = { text: string; inferred: boolean; confidence: number; approved_at: string; expires_at: string };
    const byPredicate = new Map<string, MemItem[]>();
    const seen = new Set<string>();

    const pushFact = (predicate: string, object: string, source: string, confidence: number, approved_at: string, expires_at: string) => {
      const family = memoryFactFamily(predicate);
      const meta = MEMORY_GROUPS[family];
      if (!meta || !object) return;
      if (["has_skill", "has_expertise_in", "is_learning"].includes(predicate) && !cleanTopic(object)) return;
      if (expires_at) {
        const end = Date.parse(expires_at);
        if (!Number.isNaN(end) && end <= nowMs) return;
      }
      const dedupeKey = memoryFactKey(predicate, object);
      if (seen.has(dedupeKey)) return;
      seen.add(dedupeKey);
      const list = byPredicate.get(family) ?? [];
      const rawText = ENUM_LABELS[object] ?? object;
      const text = family === "is_building" ? rawText.replace(/^building\s+/i, "") : rawText;
      list.push({ text, inferred: source === "inferred", confidence, approved_at, expires_at });
      byPredicate.set(family, list);
    };

    if (cardView) {
      for (const f of cardView.facts) {
        pushFact(f.type, f.text, f.source || "", f.confidence ?? 0, f.approved_at || "", f.expires_at || "");
      }
    } else {
      for (const f of (card.zynd_memory ?? []) as Array<Record<string, unknown>>) {
        const predicate = String(f.predicate ?? "");
        const object = String(f.object ?? "").trim();
        const approved_at = typeof f.approved_at === "string" ? f.approved_at : "";
        let expires_at = "";
        const days = HALF_LIFE_DAYS[predicate];
        if (days && approved_at) {
          const t = Date.parse(approved_at);
          if (!Number.isNaN(t)) expires_at = new Date(t + days * 86400000).toISOString();
        }
        pushFact(
          predicate,
          object,
          String(f.source ?? ""),
          typeof f.confidence === "number" ? f.confidence : 0,
          approved_at,
          expires_at,
        );
      }
    }

    return GROUP_ORDER
      .filter((p) => byPredicate.has(p))
      .map((p) => {
        const meta = MEMORY_GROUPS[p];
        const items = byPredicate.get(p)!;
        const sorted = p === "has_expertise_in"
          ? [...items].sort((a, b) => b.confidence - a.confidence)
          : [...items].sort((a, b) => b.approved_at.localeCompare(a.approved_at));
        return { key: p, label: meta.label, icon: meta.icon, items: sorted };
      });
  })();
  const memoryTotal = memoryGroups.reduce((n, g) => n + g.items.length, 0);
  const memoryFreshLabel = (() => {
    const stamps = memoryGroups.flatMap((g) => g.items.map((i) => i.expires_at).filter(Boolean));
    if (!stamps.length) return cardView?.fresh_as_of ? "LIVE" : "LIVE";
    const soonest = stamps.map((s) => Date.parse(s)).filter((n) => !Number.isNaN(n)).sort((a, b) => a - b)[0];
    if (!soonest) return "LIVE";
    const daysLeft = Math.max(0, Math.ceil((soonest - nowMs) / 86400000));
    return daysLeft <= 7 ? `${daysLeft}d left` : "LIVE";
  })();
  const firstName = identity.name?.split(" ")[0] || "They";
  const chatPrompts = [
    card.working_on.find((item) => !isBlank(item)) ? `What is ${firstName} building?` : "",
    skills.find((skill) => !isBlank(skill.name)) ? `What is ${firstName} good at?` : "",
    !isBlank(identity.headline) ? `What does ${firstName} do?` : "",
  ].filter(Boolean).slice(0, 3);
  const liJobs = (card.work_experience ?? []).filter((j) => !!(j.title || j.company));
  const nowJob = liJobs.find((j) =>
    /^(present|current|now)$/i.test((j.end_date || "").trim()) && (j.title || j.company),
  );
  const liWriting = (card.writing_samples ?? []).filter((s) => s.platform.toLowerCase() === "linkedin" && !isBlank(s.excerpt));
  const liMetrics: { val: number; label: string }[] = [];
  if (card.experience_years != null) liMetrics.push({ val: card.experience_years, label: "YEARS" });
  if (liJobs.length > 0) liMetrics.push({ val: liJobs.length, label: "ROLES" });
  if (liWriting.length > 0) liMetrics.push({ val: liWriting.length, label: "POSTS" });
  const helpWith = (card.can_help_with ?? []).filter((x) => !isBlank(x)).slice(0, 3);

  let isOwner = false;
  let isSignedIn = false;
  try {
    const supabase = await createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (session?.access_token && !visitorPreview) {
      isSignedIn = true;
      const myCard = await getMyCard(session.access_token);
      isOwner = !!(myCard && myCard.handle === handle);
    }
  } catch {
    // Auth check is best-effort
  }

  // The Connect / Message button: for visitors to a claimed Card (never the owner, never an unclaimed one).
  const showConnect = claimed && !isOwner;

  const showLinkedin = !!(linkedinHandle || linkedinUrl || liJobs.length > 0);
  const showX = !!(v.x.handle || v.x.followers != null);
  const showGithub = cardHasGithub;
  const contributions = (v.contributions && Array.isArray(v.contributions.levels) && v.contributions.levels.length > 0)
    ? v.contributions
    : ghExtras?.contributions ?? null;
  const hasContributions = !!(contributions && contributions.levels.length > 0);
  const ghFollowers = v.github.followers ?? ghExtras?.followers ?? null;
  const ghFollowing = ghExtras?.following ?? null;
  const ghBio = ghExtras?.bio;
  const ghContribTotal = contributions?.total ?? (typeof v.github.commits === "number" ? v.github.commits : null);
  const linkedinAvatarSrc = imgProxyUrl(safeUrl(card.linkedin_stats?.avatar) ?? rawAvatar, ghAvatar, card.handle || handle);
  const xAvatarSrc = imgProxyUrl(safeUrl(card.x_stats?.avatar) ?? rawAvatar, ghAvatar, card.handle || handle);
  const xImpressions = v.x.impressions != null && String(v.x.impressions).trim() !== "—" ? v.x.impressions : null;
  const showMemory = claimed && memoryTotal > 0;
  const showBooking = claimed && bookingLinks.length > 0;
  const socialSlots = [showLinkedin, showX, showMemory, showBooking].filter(Boolean).length;

  /* ── shared card style ─────────────────────────────────── */
  const card_ = "bg-white border border-[#e2e8f0] rounded-[20px] p-5 flex flex-col justify-between";
  const label_ = "flex justify-between items-center text-[0.65rem] font-mono font-bold uppercase tracking-widest text-slate-400 mb-3";
  const pill_ = "bg-[#f1f5f9] border border-[#e2e8f0] text-slate-500 text-[0.65rem] font-bold font-mono px-2.5 py-1 rounded-full";

  return (
    <>
      <ProfileView handle={handle} from={fromSearch} />
      <link rel="canonical" href={canonical} />
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      {/* eslint-disable-next-line @next/next/no-page-custom-font */}
      <link
        href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700;800&family=Space+Mono:wght@400;700&display=swap"
        rel="stylesheet"
      />
      <script
        type="application/ld+json"
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: JSON.stringify(buildJsonLd(card, cardView)).replace(/</g, "\\u003c") }}
        suppressHydrationWarning
      />

      <style>{`
        .pf-page { font-family: 'Plus Jakarta Sans', -apple-system, sans-serif; -webkit-font-smoothing: antialiased; letter-spacing: 0; line-height: 1.45; word-spacing: normal; }
        .pf-mono { font-family: 'Space Mono', monospace; }
        .pf-page a { color: inherit; text-decoration: none; }
        .pf-page a:hover { text-decoration: underline; }
        /* AutoScroll */
        .pf-vscroll { overflow: hidden; position: relative; }
        .pf-vrow { display: flex; flex-direction: column; justify-content: flex-start; flex-shrink: 0; overflow: hidden; }
        .pf-vrow-post { height: 128px; }
        .pf-clamp-2 { overflow: hidden; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
        .pf-post-excerpt { margin: 0; font-size: 13.5px; line-height: 1.55; font-weight: 500; font-style: normal; letter-spacing: 0.01em; word-spacing: 0.06em; word-break: break-word; overflow-wrap: break-word; white-space: pre-wrap; overflow: hidden; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
        .pf-quote-reel { height: 100%; display: flex; flex-direction: column; min-height: 0; }
        .pf-quote-text { margin: 0; flex: 1; min-height: 0; overflow: hidden; white-space: pre-wrap; font-size: 13.5px; line-height: 1.55; font-weight: 500; font-style: normal; letter-spacing: 0.01em; word-break: break-word; overflow-wrap: break-word; max-height: calc(1.55em * 6); }
        .pf-quote-count { margin-top: 8px; font-size: 0.58rem; letter-spacing: 0.08em; opacity: 0.55; }
        @media (prefers-reduced-motion: reduce) { .pf-vscroll { overflow-y: auto; } }
        /* bracket corners */
        .tc { position: relative; }
        .tc::before { content:''; position:absolute; top:12px; left:12px; width:8px; height:8px; border-top:1px solid #d4d4d8; border-left:1px solid #d4d4d8; }
        .tc::after  { content:''; position:absolute; top:12px; right:12px; width:8px; height:8px; border-top:1px solid #d4d4d8; border-right:1px solid #d4d4d8; }
        /* SkillMatrix / EditCardButton compat */
        .pf-edit-btn { display:inline-flex; align-items:center; gap:6px; padding:6px 14px; border-radius:999px; background:#f4f4f5; border:1px solid #E5E5DE; font-family:'Space Mono',monospace; font-size:11px; font-weight:600; color:#0B0B0B; cursor:pointer; transition:background .15s,color .15s; }
        .pf-edit-btn:hover { background:#0B0B0B; color:#fff; text-decoration:none; }
        .bento-corner { position:relative; }
        .bento-corner::after { content:''; position:absolute; top:14px; right:14px; width:14px; height:14px; border-top:2px solid currentColor; border-right:2px solid currentColor; opacity:.35; pointer-events:none; }
        .pf-book-card { position: relative; overflow: hidden; }
        .pf-book-card::before { content:''; position:absolute; width:220px; height:220px; right:-60px; top:-70px; background:radial-gradient(circle, rgba(255,255,255,0.22), transparent 68%); pointer-events:none; }
        .pf-book-cta { transition: background .15s, transform .15s, box-shadow .15s; }
        .pf-book-cta:hover { background:#f8fafc !important; text-decoration:none !important; transform:translateY(-1px); box-shadow:0 8px 20px rgba(15,23,42,0.18); }
        .pf-hero-h { font-size:0.78rem; color:#e0e7ff; font-weight:600; line-height:1.35; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; overflow:hidden; }
        /* Connect / Message pill under the name (components/network/ConnectionButton): a white pill on the purple hero, like "Open chat" */
        .pf-connect { display:flex; flex-direction:column; align-items:flex-start; gap:6px; max-width:100%; }
        .pf-connect-anchor { position:relative; display:inline-flex; max-width:100%; }
        .pf-connect-pill { display:inline-flex; align-items:center; justify-content:center; gap:6px; min-width:104px; min-height:34px; padding:7px 14px; border:0; border-radius:999px; background:#fff; color:#4f46e5; font:inherit; font-size:0.75rem; font-weight:800; line-height:1; white-space:nowrap; text-decoration:none; cursor:pointer; transition:transform .15s, box-shadow .15s, opacity .15s; }
        /* .pf-page a { color: inherit } would win over the pill and make its label white on white */
        .pf-page a.pf-connect-pill { color:#4f46e5; }
        a.pf-connect-pill:hover, button.pf-connect-pill:not([aria-disabled="true"]):not(:disabled):hover { transform:translateY(-1px); box-shadow:0 8px 18px rgba(15,23,42,0.22); text-decoration:none; }
        .pf-connect-pill:focus-visible { outline:2px solid #fff; outline-offset:2px; }
        .pf-connect-pill[aria-disabled="true"], .pf-connect-pill:disabled { opacity:.62; cursor:default; }
        .pf-connect-pill[aria-busy="true"] { opacity:.4; }
        .pf-connect-note { max-width:100%; font-size:0.68rem; font-weight:600; line-height:1.4; color:rgba(255,255,255,0.88); overflow-wrap:anywhere; }
        .pf-connect-note a { color:#fff; text-decoration:underline; }
        .pf-connect-pop { position:absolute; z-index:40; top:calc(100% + 8px); box-sizing:border-box; padding:12px; border:1px solid #e5e7eb; border-radius:14px; background:#fff; color:#0f172a; box-shadow:0 18px 40px rgba(15,23,42,0.28); text-align:left; }
        .pf-connect-pop-text { margin:0 0 8px; font-size:0.72rem; line-height:1.4; color:#64748b; }
        .pf-connect-pop-note { display:block; width:100%; box-sizing:border-box; min-height:72px; padding:9px 10px; border:1px solid #d4d4d8; border-radius:10px; background:#fff; color:#0f172a; font:inherit; font-size:0.8rem; resize:vertical; }
        .pf-connect-pop-note:focus-visible { outline:2px solid #6d64f6; outline-offset:1px; }
        .pf-connect-pop-actions { display:flex; align-items:center; gap:8px; margin-top:8px; }
        .pf-connect-send { border:0; border-radius:999px; padding:8px 14px; background:#6d64f6; color:#fff; font:inherit; font-size:0.75rem; font-weight:800; cursor:pointer; }
        .pf-connect-send:disabled { opacity:.6; cursor:default; }
        .pf-connect-cancel { border:0; background:transparent; padding:8px 6px; color:#64748b; font:inherit; font-size:0.75rem; font-weight:700; cursor:pointer; }
        .pf-connect-pop-error { margin:8px 0 0; font-size:0.72rem; line-height:1.4; color:#b91c1c; }
        /* On an edition card the identity card is white, so the button takes the edition accent and sits at the end of the actions */
        .pf-connect.is-edition { align-items:flex-end; }
        .pf-connect.is-edition .pf-connect-pill { min-height:44px; padding:13px 22px; border-radius:12px; background:var(--ed-accent, #6C5CE7); color:#fff; font:700 15px/1 var(--ed-ui), system-ui, sans-serif; box-shadow:0 12px 24px -14px rgba(108,92,231,0.9); }
        .pf-connect.is-edition .pf-connect-pill:focus-visible { outline-color:var(--ed-accent, #6C5CE7); }
        .pf-connect.is-edition .pf-connect-note { color:var(--ed-soft, #5B5B7E); text-align:right; }
        .pf-connect.is-edition .pf-connect-note a { color:var(--ed-accent, #6C5CE7); }
        /* Desktop grid layout — defined in CSS so @media can override without fighting inline styles */
        .pf-main-grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 16px; align-items: stretch; }
        .pf-hero { grid-column: span 4; padding: 18px; height: 100%; }
        .pf-right-stack { grid-column: span 8; display: flex; flex-direction: column; gap: 16px; height: 100%; }
        .pf-ai-work { display: grid; grid-template-columns: repeat(12, 1fr); gap: 16px; align-items: stretch; }
        .pf-ai-work > *:only-child { grid-column: 1 / -1; }
        .pf-ai-fact { grid-column: span 5; padding: 20px 24px; height: 100%; min-height: 0; }
        .pf-work { grid-column: span 7; height: 100%; min-height: 0; }
        .pf-span-12 { grid-column: span 12; }
        .pf-social-row { display: grid; grid-template-columns: var(--social-cols, repeat(2, minmax(0, 1fr))); gap: 16px; align-items: stretch; }
        .pf-social-card { height: 100%; display: flex; flex-direction: column; min-width: 0; }
        .pf-social-id { display: flex; align-items: center; gap: 10px; margin-top: 12px; min-height: 48px; }
        .pf-social-mid { margin-top: 12px; padding-top: 12px; flex: 1; min-height: 0; }
        .pf-social-cta { margin-top: auto; display: flex; align-items: center; justify-content: center; min-height: 36px; padding: 9px 14px; border-radius: 10px; font-size: 0.68rem; font-weight: 700; text-decoration: none; }
        .pf-obs-row { display: grid; grid-template-columns: var(--obs-cols, 1fr); gap: 16px; }
        .pf-gh-row { display: grid; grid-template-columns: var(--gh-cols, 1fr 1fr); gap: 16px; }
        .pf-proj-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; align-items: start; }
        .pf-gallery-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 0; padding: 0; list-style: none; }
        .pf-gallery-tile { position: relative; aspect-ratio: 4 / 3; overflow: hidden; border-radius: 14px; border: 1px solid #e2e8f0; background: #e2e8f0; }
        .pf-gallery-tile a { display: block; width: 100%; height: 100%; }
        .pf-gallery-tile img { display: block; width: 100%; height: 100%; object-fit: cover; transition: transform .25s ease; }
        .pf-gallery-tile a:hover img { transform: scale(1.04); }
        .pf-gallery-title { position: absolute; inset: auto 0 0 0; padding: 24px 12px 9px; background: linear-gradient(transparent, rgba(15, 23, 42, .72)); color: #fff; font-size: .72rem; font-weight: 700; line-height: 1.3; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        @media (max-width: 820px) {
          .pf-page { overflow-x: hidden; }
          .pf-inner { padding: 12px 12px 72px !important; }
          /* Nav: single row — hide verbose badge, keep breadcrumb + Share + QR */
          .pf-synthesis-badge { display: none; }
          .pf-header { flex-direction: row !important; align-items: center !important; gap: 8px; flex-wrap: wrap; }
          .pf-header-actions { width: auto !important; justify-content: flex-end !important; flex-wrap: nowrap !important; }
          /* Stack: main grid, ai-work sub-grid, github row */
          .pf-main-grid,
          .pf-ai-work,
          .pf-gh-row {
            grid-template-columns: 1fr;
            gap: 12px;
          }
          /* Obsessions: 2-col bento, equal height */
          .pf-obs-row { grid-template-columns: 1fr 1fr; gap: 10px; align-items: stretch; }
          /* Solo or odd-trailing obs card → full width */
          .pf-obs-row > *:only-child,
          .pf-obs-row > *:last-child:nth-child(odd) { grid-column: 1 / -1; }
          /* Cards: stack from top; chips fill remaining space and scroll invisibly if overflow */
          .pf-obs-card { justify-content: flex-start !important; gap: 10px; }
          .pf-obs-chips { flex: 1; min-height: 0; overflow-y: auto; scrollbar-width: none; }
          .pf-obs-chips::-webkit-scrollbar { display: none; }
          /* Social cards: 1-col by default */
          .pf-social-row { grid-template-columns: 1fr; gap: 12px; }
          /* 3+ cards: LinkedIn+X side-by-side equal height, Calendly full-width below */
          .pf-social-row:has(> *:nth-child(3)) { grid-template-columns: 1fr 1fr; gap: 10px; }
          .pf-social-row:has(> *:nth-child(3)) > *:not(.pf-book-card) { align-self: stretch; justify-content: space-between; }
          .pf-social-row:has(> *:nth-child(3)) > .pf-book-card { grid-column: 1 / -1; }
          /* Projects + Skills: too cramped at 2-col on mobile — stack full-width */
          .pf-proj-row { grid-template-columns: 1fr; gap: 12px; }
          .pf-gallery { padding: 16px !important; }
          .pf-gallery-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
          /* Skill grid gets full card width — use 3-col */
          .pf-skill-grid { grid-template-columns: repeat(3, minmax(0, 1fr)) !important; }
          .pf-hero,
          .pf-right-stack,
          .pf-span-12,
          .pf-ai-fact,
          .pf-work {
            grid-column: 1 / -1;
            width: 100%;
            min-width: 0;
          }
          .pf-hero { height: auto; padding: 16px; }
          .pf-hero-avatar { width: 72px !important; height: 72px !important; }
          .pf-hero-name { font-size: clamp(1.1rem, 4.5vw, 1.45rem) !important; }
          /* Connect pill: a thumb-sized target; on an edition card it spans the actions like the buttons beside it */
          .pf-connect-pill { min-height: 40px; }
          .pf-connect.is-edition { align-items: stretch; }
          .pf-connect.is-edition .pf-connect-anchor { display: flex; }
          .pf-connect.is-edition .pf-connect-pill { flex: 1; }
          .pf-connect.is-edition .pf-connect-note { text-align: left; }
          .pf-right-stack { height: auto; gap: 12px; }
          .pf-code { overflow-x: auto; -webkit-overflow-scrolling: touch; font-size: 0.65rem !important; }
          .pf-code > div { word-break: break-word; overflow-wrap: anywhere; }
          .pf-ai-fact { padding: 16px; }
          /* GitHub heatmap card: let wide SVG scroll rather than squish */
          .pf-gh-row > *:last-child { overflow-x: auto; -webkit-overflow-scrolling: touch; }
          .pf-gh-stats { grid-template-columns: 1fr 1fr 1fr 1fr !important; }
          .pf-li-stats { grid-template-columns: 1fr 1fr !important; }
          /* x stats: keep 3-col when impressions present — short numbers fit fine */
          .pf-x-stats { grid-template-columns: 1fr 1fr !important; }
          .pf-x-stats-3 { grid-template-columns: repeat(3, minmax(0, 1fr)) !important; }
          .pf-cta { flex-direction: column; align-items: stretch !important; padding: 20px 16px !important; }
          .pf-cta a { width: 100%; justify-content: center !important; }
          .pf-posts { padding: 16px !important; }
          .pf-post-excerpt { font-size: 12.5px !important; }
          .pf-book-week { overflow-x: auto; }
          .pf-book-badges { flex-wrap: wrap !important; gap: 6px !important; }
          .pf-footer { flex-direction: column; align-items: flex-start !important; }
          .pf-footer-links { flex-wrap: wrap !important; gap: 8px !important; }
          .pf-permalink-badge { flex: 1 1 100%; max-width: calc(100vw - 48px) !important; min-width: 0 !important; overflow: hidden !important; }
          .pf-permalink-text { overflow: hidden !important; text-overflow: ellipsis !important; white-space: nowrap !important; max-width: 160px !important; }
          .pf-social-head { flex-wrap: wrap; gap: 6px; }
          /* nowrap + ellipsis so long handles like "in/very-long-username" truncate cleanly */
          .pf-social-head a { white-space: nowrap !important; overflow: hidden !important; text-overflow: ellipsis !important; max-width: 55% !important; }
          .pf-social-head span { max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
          /* project description: 2-line wrap beats single-line truncation on wide mobile */
          .pf-proj-desc { white-space: normal !important; display: -webkit-box !important; -webkit-box-orient: vertical !important; -webkit-line-clamp: 2 !important; text-overflow: clip !important; }
        }
      `}</style>

      <div className={edition ? "pf-page ed-page" : "pf-page"} style={{ backgroundColor: edition ? "#F3F1FB" : "#f5f6f8", minHeight: "100vh" }}>
        <div className="pf-inner" style={{ maxWidth: 1300, margin: "0 auto", padding: "24px 24px 56px" }}>

          {/* ── UNCLAIMED BANNER ── */}
          {!claimed && (
            <ClaimBanner handle={card.handle ?? handle} name={identity.name} />
          )}

          {/* ── HEADER ── */}
          <header className="pf-header flex justify-between items-center pb-5">
            <div className="pf-mono text-[0.75rem] text-slate-500">
              <Link href="/directory" className="hover:text-slate-800">Zynd</Link>
              {" / "}
              <Link href="/directory" className="hover:text-slate-800">Directory</Link>
              {" / "}
              <strong className="text-slate-800">@{card.handle || card.id}</strong>
            </div>
            <div className="pf-header-actions flex gap-2.5 items-center flex-wrap justify-end">
              {!claimed && (
                <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-amber-50 border border-amber-200 text-[0.7rem] pf-mono font-bold text-amber-700">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                  UNCLAIMED
                </span>
              )}
              <ShareQrGroup
                url={canonical}
                name={identity.name || "Profile"}
                handle={card.handle ?? card.id}
                avatarUrl={heroAvatarSrc ?? avatarUrl}
                resume={resumeData}
                headline={identity.headline}
                alias={card.alias}
              />
              {isOwner && <EditCardButton handle={card.handle ?? card.id} />}
              {!isSignedIn && <ProfileSignIn handle={card.handle ?? handle} />}
              {isSignedIn && !isOwner && <ClaimCardButton handle={card.handle ?? handle} card={card} />}
              {isSignedIn && <ProfileAccountChip />}
            </div>
          </header>

          {edition && (
            <EditionHero
              edition={edition}
              name={identity.name || card.handle || "Profile"}
              nameLines={nameLines}
              headline={isBlank(identity.headline) ? "" : identity.headline}
              location={isBlank(identity.location) ? "" : identity.location}
              role={nowJob ? [nowJob.title, nowJob.company].filter(Boolean).join(" · ") : ""}
              chips={[...helpWith, ...(card.industries ?? []).filter((x) => !isBlank(x))].slice(0, 6)}
              avatarSrc={heroAvatarSrc ?? null}
              initials={initials}
              url={canonical}
              permalink={permalink}
              handle={card.handle ?? card.id}
              verified={linkedinLinked}
              canChat={claimed}
              connect={showConnect ? <ConnectionButton key={card.handle ?? handle} handle={card.handle ?? handle} name={identity.name || undefined} variant="edition" /> : null}
              about={isBlank(card.summary) ? "" : card.summary}
              links={{ x: safeUrl(identity.links?.x), github: safeUrl(identity.links?.github), linkedin: safeUrl(identity.links?.linkedin) }}
              updatedLabel={syncedAt}
            />
          )}

          {/* ── MAIN GRID ── */}
          <div className="pf-main-grid">

            {/* ── HERO CARD (4 col): the edition's identity card above replaces it ── */}
            {!edition && (
            <div
              className="pf-hero"
              style={{ background: "#6d64f6", borderRadius: 20, color: "#fff", display: "flex", flexDirection: "column", minHeight: 0 }}
            >
              <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
                {heroAvatarSrc ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={heroAvatarSrc}
                    alt={identity.name}
                    className="pf-hero-avatar"
                    style={{ width: 104, height: 104, borderRadius: 18, border: "2px solid rgba(255,255,255,0.35)", objectFit: "cover", flexShrink: 0, display: "block" }}
                  />
                ) : (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="104" height="104"><rect width="104" height="104" rx="18" fill="rgba(255,255,255,0.18)"/><text x="52" y="58" text-anchor="middle" dominant-baseline="middle" fill="#fff" font-family="system-ui,sans-serif" font-size="32" font-weight="800">${initials}</text></svg>`)}`}
                    alt={identity.name}
                    width={104}
                    height={104}
                    className="pf-hero-avatar"
                    style={{ width: 104, height: 104, borderRadius: 18, flexShrink: 0, display: "block" }}
                  />
                )}
                <div style={{ minWidth: 0, flex: 1, paddingTop: 4 }}>
                  <div style={{ fontSize: "0.72rem", fontWeight: 600, opacity: 0.8 }}>I&apos;m</div>
                  <div className="pf-hero-name" style={{ fontSize: "1.45rem", fontWeight: 800, lineHeight: 1.05, margin: "2px 0 0", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span>{nameLines.map((line, i) => <span key={i}>{line}{i < nameLines.length - 1 ? " " : ""}</span>)}</span>
                    {linkedinLinked && (
                      <BadgeCheck size={22} color="#FBBF24" fill="#FBBF24" stroke="#6d64f6" strokeWidth={1.5} aria-label="LinkedIn linked" />
                    )}
                  </div>
                  {showConnect && (
                    <div style={{ marginTop: 10 }}>
                      <ConnectionButton key={card.handle ?? handle} handle={card.handle ?? handle} name={identity.name || undefined} />
                    </div>
                  )}
                </div>
              </div>
              {!isBlank(identity.headline) && (
                <div className="pf-hero-h" style={{ marginTop: 12 }}>{identity.headline}</div>
              )}
              {(nowJob || !isBlank(identity.location)) && (
                <div style={{ marginTop: 8, fontSize: "0.72rem", color: "rgba(255,255,255,0.78)", fontWeight: 600, lineHeight: 1.4 }}>
                  {nowJob && <div>{[nowJob.title, nowJob.company].filter(Boolean).join(" · ")}</div>}
                  {!isBlank(identity.location) && <div style={{ fontWeight: 500, opacity: 0.85 }}>{identity.location}</div>}
                </div>
              )}
              {helpWith.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 10 }}>
                  {helpWith.map((item) => (
                    <span key={item} style={{ background: "rgba(255,255,255,0.16)", borderRadius: 999, padding: "3px 8px", fontSize: "0.62rem", fontWeight: 600 }}>
                      {item}
                    </span>
                  ))}
                </div>
              )}

              {claimed && <HeroAskPanel firstName={firstName} handle={card.handle || handle} permalink={permalink} />}

              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
                <div style={{ display: "flex", gap: 8 }}>
                  {identity.links?.x && (
                    <a href={safeUrl(identity.links.x) ?? "#"} target="_blank" rel="noreferrer" style={{ width: 28, height: 28, borderRadius: "50%", background: "rgba(255,255,255,0.18)", display: "flex", alignItems: "center", justifyContent: "center" }} aria-label="X">
                      <XGlyph size={12} />
                    </a>
                  )}
                  {identity.links?.github && (
                    <a href={safeUrl(identity.links.github) ?? "#"} target="_blank" rel="noreferrer" style={{ width: 28, height: 28, borderRadius: "50%", background: "rgba(255,255,255,0.18)", display: "flex", alignItems: "center", justifyContent: "center" }} aria-label="GitHub">
                      <GithubGlyph size={13} />
                    </a>
                  )}
                  {identity.links?.linkedin && (
                    <a href={safeUrl(identity.links.linkedin) ?? "#"} target="_blank" rel="noreferrer" style={{ width: 28, height: 28, borderRadius: "50%", background: "rgba(255,255,255,0.18)", display: "flex", alignItems: "center", justifyContent: "center" }} aria-label="LinkedIn">
                      <LinkedinGlyph size={13} />
                    </a>
                  )}
                </div>
                <div className="pf-mono" style={{ fontSize: "0.62rem", color: "rgba(255,255,255,0.62)" }}>
                  {syncedAt && <>Updated {syncedAt}</>}
                </div>
              </div>
            </div>
            )}

            {/* ── RIGHT STACK: Dossier + Signals (8 col); edition cards draw their own ── */}
            {edition && (
              <EditionSignals
                signals={obsessions.map((obs) => ({ key: obs.key, label: obs.label, items: obs.items.filter((item) => !isBlank(item)) }))}
              />
            )}
            {!edition && (
            <div className="pf-right-stack">

              {/* Dossier */}
              {!isBlank(card.summary) && (
                <div className={`${card_} tc`}>
                  <div>
                    <div className={label_}>
                      <span>┌ ABOUT</span>
                      <span>┐</span>
                    </div>
                    <p style={{ fontSize: "0.85rem", color: "#0f172a", fontWeight: 600, lineHeight: 1.65, marginBottom: 16 }}>
                      {card.summary}
                    </p>
                  </div>
                  {card.industries && card.industries.length > 0 && (
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      {card.industries.slice(0, 5).map((tag) => (
                        <span key={tag} className={pill_}>{tag}</span>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Signal cards row */}
              {obsessions.length > 0 && (
                <div className="pf-obs-row" style={{ "--obs-cols": `repeat(${obsessions.length}, 1fr)` } as React.CSSProperties}>
                  {obsessions.map((obs) => (
                    <div key={obs.key} className={`pf-obs-card ${obs.card} rounded-[20px] p-[18px] flex flex-col justify-between`}>
                      <div className={`${label_} pf-mono`} style={{ color: "inherit", opacity: 0.8 }}>
                        <span>┌ {obs.label.toUpperCase()}</span>
                        <span className={`${obs.chip} text-[0.6rem] px-2 py-0.5 rounded-full font-mono font-bold`}>
                          {obsessionSources[obs.key].length} {obs.unit}
                        </span>
                      </div>
                      <div className="pf-obs-chips" style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 6 }}>
                        {obsessionSources[obs.key].slice(0, 4).map((item) => (
                          <span key={item} className={`${obs.chip} text-[0.65rem] font-bold font-mono px-2.5 py-1 rounded-full`}>
                            {item}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            )}

            {/* ── AI FACT + WORK EXP: equal height, fact card fills ── */}
            {claimed && card.beacon && Date.parse(card.beacon.created_at) <= nowMs && Date.parse(card.beacon.expires_at) > nowMs && <BeaconCard key={card.beacon.expires_at} beacon={card.beacon} />}
            <div className="pf-span-12 pf-ai-work">
            {claimed && (() => {
              const q = (s: string) => `"${s.replace(/"/g, '\\"')}"`;
              const arr = (items: string[]) => `[${items.map(q).join(", ")}]`;
              const currentRoles = (card.work_experience ?? [])
                .filter((j) => /^(present|current|now)$/i.test((j.end_date || "").trim()) && (j.title || j.company))
                .map((j) => j.title || j.company)
                .slice(0, 3);
              const tech = skills.slice(0, 5).map((s) => s.name);
              const industries = (card.industries ?? []).filter((x) => !isBlank(x)).slice(0, 4);
              const help = (card.can_help_with ?? []).filter((x) => !isBlank(x)).slice(0, 3);
              return (
            <div className="pf-ai-fact" style={{ background: "#0f172a", borderRadius: 20, color: "#fff", display: "flex", flexDirection: "column" }}>
              <div className="pf-mono flex justify-between items-center" style={{ fontSize: "0.65rem", color: "#94a3b8", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                <span>FOR AI AGENTS</span>
                <span style={{ background: "rgba(255,255,255,0.1)", color: "#e2e8f0", padding: "3px 10px", borderRadius: 99 }}>ZYND</span>
              </div>
              <div className="pf-mono pf-code" style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 12, padding: "16px 18px", fontSize: "0.72rem", lineHeight: 1.45, margin: "14px 0 0", flex: 1, minHeight: 0, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
                <div style={{ color: "#64748b" }}>{"// machine-readable profile"}</div>
                <div><span style={{ color: "#38bdf8" }}>entity</span><span style={{ color: "#94a3b8" }}>:</span> <span style={{ color: "#fde047" }}>{q(identity.name)}</span></div>
                {!isBlank(identity.headline) && (
                  <div><span style={{ color: "#38bdf8" }}>role</span><span style={{ color: "#94a3b8" }}>:</span> <span style={{ color: "#fde047" }}>{q(identity.headline)}</span></div>
                )}
                {!isBlank(identity.location) && (
                  <div><span style={{ color: "#38bdf8" }}>location</span><span style={{ color: "#94a3b8" }}>:</span> <span style={{ color: "#fde047" }}>{q(identity.location)}</span></div>
                )}
                {card.experience_years != null && (
                  <div><span style={{ color: "#38bdf8" }}>experience</span><span style={{ color: "#94a3b8" }}>:</span> <span style={{ color: "#86efac" }}>{card.experience_years}</span><span style={{ color: "#94a3b8" }}> years</span></div>
                )}
                {!isBlank(card.availability) && (
                  <div><span style={{ color: "#38bdf8" }}>availability</span><span style={{ color: "#94a3b8" }}>:</span> <span style={{ color: "#fde047" }}>{q(card.availability)}</span></div>
                )}
                {currentRoles.length > 0 && (
                  <div><span style={{ color: "#38bdf8" }}>current_roles</span><span style={{ color: "#94a3b8" }}>:</span> <span style={{ color: "#fde047" }}>{arr(currentRoles)}</span></div>
                )}
                {tech.length > 0 && (
                  <div><span style={{ color: "#38bdf8" }}>primary_tech</span><span style={{ color: "#94a3b8" }}>:</span> <span style={{ color: "#fde047" }}>{arr(tech)}</span></div>
                )}
                {industries.length > 0 && (
                  <div><span style={{ color: "#38bdf8" }}>industries</span><span style={{ color: "#94a3b8" }}>:</span> <span style={{ color: "#fde047" }}>{arr(industries)}</span></div>
                )}
                {help.length > 0 && (
                  <div><span style={{ color: "#38bdf8" }}>can_help_with</span><span style={{ color: "#94a3b8" }}>:</span> <span style={{ color: "#fde047" }}>{arr(help)}</span></div>
                )}
              </div>
              <div className="pf-mono" style={{ fontSize: "0.65rem", color: "#64748b", paddingTop: 12, lineHeight: 1.5, flexShrink: 0 }}>
                AI assistants (ChatGPT, Claude, Perplexity) can read this profile and recommend {firstName}.
              </div>
            </div>
              );
            })()}

            <WorkExperienceCard
              jobs={(card.work_experience ?? []).filter((j) => !!(j.title || j.company))}
              experienceYears={card.experience_years}
              linkedinHandle={linkedinHandle}
              linkedinUrl={linkedinUrl}
              cardClass={card_}
              labelClass={label_}
              pillClass={pill_}
            />
            </div>

            {/* ── SOCIAL ROW: equal columns, always fills the 12-col track ── */}
            {socialSlots > 0 && (
            <div className="pf-span-12 pf-social-row" style={{ "--social-cols": `repeat(${Math.max(socialSlots, 2)}, minmax(0, 1fr))` } as React.CSSProperties}>

            {/* ── SOCIAL: LINKEDIN ── */}
            {showLinkedin && (
              <div
                className="pf-social-card"
                data-ed-card="linkedin"
                style={{ background: "#0A66C2", borderRadius: 20, padding: 16, color: "#fff", overflow: "hidden" }}
              >
                <div className="pf-mono pf-social-head flex justify-between items-center" style={{ fontSize: "0.65rem", fontWeight: 700, minHeight: 18 }}>
                  <span className="flex items-center gap-1"><LinkedinGlyph size={12} /> LINKEDIN</span>
                  {linkedinUrl ? (
                    <a href={linkedinUrl} target="_blank" rel="noreferrer" style={{ opacity: 0.7 }}>
                      {linkedinHandle ? `in/${linkedinHandle} ↗` : "Profile ↗"}
                    </a>
                  ) : linkedinHandle ? (
                    <span style={{ opacity: 0.7 }}>in/{linkedinHandle}</span>
                  ) : null}
                </div>
                <div className="pf-social-id">
                  {linkedinAvatarSrc ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={linkedinAvatarSrc} alt="" style={{ width: 44, height: 44, borderRadius: "50%", objectFit: "cover", border: "2px solid rgba(255,255,255,0.35)", flexShrink: 0 }} />
                  ) : (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="44" height="44"><circle cx="22" cy="22" r="22" fill="rgba(255,255,255,0.2)"/><text x="22" y="24" text-anchor="middle" dominant-baseline="middle" fill="#fff" font-family="system-ui" font-size="14" font-weight="800">${initials}</text></svg>`)}`} alt="" width={44} height={44} style={{ width: 44, height: 44, borderRadius: "50%", flexShrink: 0 }} />
                  )}
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: "1.05rem", fontWeight: 800, lineHeight: 1.2 }}>{identity.name}</div>
                    <div className="pf-clamp-2" style={{ fontSize: "0.7rem", opacity: 0.8, marginTop: 3, fontWeight: 600, minHeight: "2.1em" }}>{!isBlank(identity.headline) ? identity.headline : "\u00a0"}</div>
                  </div>
                </div>
                <div className="pf-mono pf-li-stats pf-social-mid" style={{ display: "grid", gridTemplateColumns: liMetrics.length > 1 ? `repeat(${Math.min(liMetrics.length, 3)}, 1fr)` : "1fr", gap: 8, borderTop: "1px solid rgba(255,255,255,0.18)" }}>
                  {liMetrics.length > 0 ? liMetrics.slice(0, 3).map((m) => (
                    <div key={m.label}>
                      <strong style={{ fontSize: "1.15rem", display: "block", color: "#fff" }}><CountUp value={m.val} /></strong>
                      <span style={{ fontSize: "0.58rem", opacity: 0.75 }}>{m.label}</span>
                    </div>
                  )) : nowJob ? (
                    <div>
                      <strong style={{ fontSize: "0.85rem", display: "block", color: "#fff", fontWeight: 700 }}>{nowJob.title || nowJob.company}</strong>
                      <span style={{ fontSize: "0.58rem", opacity: 0.75 }}>{nowJob.title && nowJob.company ? nowJob.company : "CURRENT ROLE"}</span>
                    </div>
                  ) : (
                    <div>
                      <strong style={{ fontSize: "0.85rem", display: "block", color: "#fff", fontWeight: 700 }}>LinkedIn</strong>
                      <span style={{ fontSize: "0.58rem", opacity: 0.75 }}>PROFILE</span>
                    </div>
                  )}
                </div>
                {linkedinUrl ? (
                  <a href={linkedinUrl} target="_blank" rel="noreferrer" className="pf-mono pf-social-cta" style={{ background: "rgba(255,255,255,0.14)" }}>
                    View LinkedIn profile →
                  </a>
                ) : (
                  <div className="pf-social-cta" />
                )}
              </div>
            )}

            {/* ── SOCIAL: X / TWITTER ── */}
            {showX && (
              <div
                className="pf-social-card"
                data-ed-card="x"
                style={{ background: "#090a0f", borderRadius: 20, padding: 16, color: "#fff", overflow: "hidden" }}
              >
                <div className="pf-mono pf-social-head flex justify-between items-center" style={{ fontSize: "0.65rem", fontWeight: 700, minHeight: 18 }}>
                  <span className="flex items-center gap-1"><XGlyph size={11} /> X / TWITTER</span>
                  {xUrl ? (
                    <a href={xUrl} target="_blank" rel="noreferrer" style={{ opacity: 0.7 }}>
                      {v.x.handle ?? "Profile"} ↗
                    </a>
                  ) : v.x.handle ? (
                    <span style={{ opacity: 0.7 }}>{v.x.handle}</span>
                  ) : null}
                </div>
                <div className="pf-social-id">
                  {xAvatarSrc ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={xAvatarSrc} alt="" style={{ width: 44, height: 44, borderRadius: "50%", objectFit: "cover", border: "2px solid rgba(255,255,255,0.2)", flexShrink: 0 }} />
                  ) : (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="44" height="44"><circle cx="22" cy="22" r="22" fill="rgba(255,255,255,0.12)"/><text x="22" y="24" text-anchor="middle" dominant-baseline="middle" fill="#fff" font-family="system-ui" font-size="14" font-weight="800">${initials}</text></svg>`)}`} alt="" width={44} height={44} style={{ width: 44, height: 44, borderRadius: "50%", flexShrink: 0 }} />
                  )}
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: "1.05rem", fontWeight: 800, lineHeight: 1.2 }}>{identity.name}</div>
                    <div className="pf-mono pf-clamp-2" style={{ fontSize: "0.7rem", opacity: 0.65, marginTop: 3, minHeight: "2.1em" }}>{v.x.handle || "\u00a0"}</div>
                  </div>
                </div>
                <div className={`pf-mono pf-social-mid pf-x-stats${xImpressions != null ? " pf-x-stats-3" : ""}`} style={{ display: "grid", gridTemplateColumns: xImpressions != null ? "1fr 1fr 1fr" : "1fr 1fr", gap: 8, borderTop: "1px solid rgba(255,255,255,0.1)" }}>
                  <div>
                    <strong style={{ fontSize: "1.15rem", display: "block", color: "#fff" }}>{v.x.followers != null ? <CountUp value={v.x.followers} /> : "—"}</strong>
                    <span style={{ fontSize: "0.58rem", opacity: 0.6 }}>FOLLOWERS</span>
                  </div>
                  <div>
                    <strong style={{ fontSize: "1.15rem", display: "block", color: "#fff" }}>{v.x.posts != null ? <CountUp value={v.x.posts} /> : "—"}</strong>
                    <span style={{ fontSize: "0.58rem", opacity: 0.6 }}>POSTS</span>
                  </div>
                  {xImpressions != null && (
                    <div>
                      <strong style={{ fontSize: "1.15rem", display: "block", color: "#fff" }}><CountUp value={xImpressions} /></strong>
                      <span style={{ fontSize: "0.58rem", opacity: 0.6 }}>IMPRESSIONS</span>
                    </div>
                  )}
                </div>
                {xUrl ? (
                  <a href={xUrl} target="_blank" rel="noreferrer" className="pf-mono pf-social-cta" style={{ background: "rgba(255,255,255,0.08)" }}>
                    View X profile →
                  </a>
                ) : (
                  <div className="pf-social-cta" />
                )}
              </div>
            )}

            {/* ── SOCIAL: ZYND MEMORY ── */}
            {showMemory && (
              <MemoryCard firstName={firstName} groups={memoryGroups} total={memoryTotal} freshLabel={memoryFreshLabel} />
            )}

            {/* ── BOOK A CALL (only when a Calendly or Google Calendar link exists) ── */}
            {showBooking && (
              <div
                className="pf-book-card pf-social-card"
                data-ed-card="booking"
                style={{ background: "linear-gradient(160deg, #2563eb 0%, #1d4ed8 48%, #1e3a8a 100%)", borderRadius: 20, padding: 16, color: "#fff" }}
              >
                <div className="pf-mono flex justify-between items-center" style={{ fontSize: "0.65rem", fontWeight: 700, letterSpacing: "0.08em", position: "relative", minHeight: 18 }}>
                  <span className="flex items-center gap-1.5"><Calendar size={12} /> BOOK A CALL</span>
                  <span style={{ background: "rgba(255,255,255,0.16)", border: "1px solid rgba(255,255,255,0.22)", borderRadius: 99, padding: "3px 8px", fontSize: "0.58rem" }}>OPEN</span>
                </div>

                <div className="pf-social-id" style={{ position: "relative" }}>
                  <div style={{ width: 44, height: 44, borderRadius: 12, background: "rgba(255,255,255,0.16)", border: "1px solid rgba(255,255,255,0.22)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                    <Calendar size={18} />
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: "1.05rem", fontWeight: 800, lineHeight: 1.2 }}>Meet {firstName}</div>
                    <div className="pf-clamp-2" style={{ fontSize: "0.7rem", opacity: 0.8, marginTop: 3, minHeight: "2.1em" }}>20-min intro · collab, projects, ideas</div>
                  </div>
                </div>

                <div className="pf-social-mid" style={{ position: "relative" }}>
                <div className="pf-book-badges" style={{ display: "flex", gap: 6 }}>
                  <span className="pf-mono" style={{ display: "inline-flex", alignItems: "center", gap: 4, background: "rgba(255,255,255,0.12)", borderRadius: 8, padding: "5px 8px", fontSize: "0.6rem", fontWeight: 700 }}>
                    <Clock size={10} /> 20 MIN
                  </span>
                  <span className="pf-mono" style={{ display: "inline-flex", alignItems: "center", gap: 4, background: "rgba(255,255,255,0.12)", borderRadius: 8, padding: "5px 8px", fontSize: "0.6rem", fontWeight: 700 }}>
                    <Video size={10} /> VIDEO
                  </span>
                  <span className="pf-mono" style={{ background: "rgba(255,255,255,0.12)", borderRadius: 8, padding: "5px 8px", fontSize: "0.6rem", fontWeight: 700 }}>1:1</span>
                </div>

                <BookingAvailability url={bookingLinks[0].url} name={firstName} />
                </div>

                {/* One link: the usual CTA. Both: one button per provider. */}
                <div style={{ display: "flex", gap: 8, marginTop: "auto" }}>
                  {bookingLinks.map((l) => (
                    <a
                      key={l.label}
                      href={l.url}
                      target="_blank"
                      rel="noreferrer"
                      className="pf-book-cta pf-mono pf-social-cta"
                      style={{ flex: 1, gap: 8, background: "#fff", color: "#1e3a8a", cursor: "pointer", letterSpacing: "0.04em" }}
                    >
                      {bookingLinks.length > 1 ? l.label : "Book intro call"}
                      <span aria-hidden>→</span>
                    </a>
                  ))}
                </div>
              </div>
            )}

            </div>
            )}

            {/* ── GITHUB: stats + heatmap fill the row; stats stretch if no graph ── */}
            {showGithub && (
              <div
                className="pf-span-12 pf-gh-row"
                style={{ "--gh-cols": hasContributions ? "minmax(240px, 4fr) minmax(0, 8fr)" : "minmax(0, 1fr) minmax(0, 1fr)" } as React.CSSProperties}
              >
                <div className={`${card_} tc`}>
                  <div>
                    <div className={`${label_} pf-mono`}>
                      <span className="flex items-center gap-1.5"><GithubGlyph size={13} />GITHUB</span>
                      {githubUrl ? (
                        <a href={githubUrl} target="_blank" rel="noreferrer" className="hover:underline">@{githubHandle} ↗</a>
                      ) : (
                        <span>@{githubHandle}</span>
                      )}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
                      <FallbackAvatar
                        src={imgProxyUrl(githubAvatar(githubUrl, 80) ?? `https://github.com/${encodeURIComponent(ghLogin || githubHandle)}.png?size=80`, undefined, card.handle || handle) ?? ""}
                        alt=""
                        initials={initials}
                        size={44}
                      />
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: "0.95rem", fontWeight: 800, color: "#0f172a" }}>{identity.name}</div>
                        {ghBio && (
                          <div className="pf-clamp-2" style={{ fontSize: "0.7rem", color: "#64748b", marginTop: 2, lineHeight: 1.4, whiteSpace: "normal" }}>{ghBio}</div>
                        )}
                      </div>
                    </div>
                    <div className="pf-gh-stats" style={{ display: "grid", gridTemplateColumns: hasContributions ? "1fr 1fr" : "repeat(4, minmax(0, 1fr))", gap: 8, marginBottom: 12 }}>
                      {v.github.repos != null && (
                        <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 12, padding: "10px 10px", textAlign: "center" }}>
                          <div style={{ fontSize: "1.15rem", fontWeight: 800, color: "#0f172a", lineHeight: 1 }}><CountUp value={v.github.repos} /></div>
                          <div className="pf-mono" style={{ fontSize: "0.55rem", color: "#94a3b8", fontWeight: 700, marginTop: 4 }}>REPOS</div>
                        </div>
                      )}
                      {v.github.activeRepos != null && (
                        <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 12, padding: "10px 10px", textAlign: "center" }}>
                          <div style={{ fontSize: "1.15rem", fontWeight: 800, color: "#0f172a", lineHeight: 1 }}><CountUp value={v.github.activeRepos} /></div>
                          <div className="pf-mono" style={{ fontSize: "0.55rem", color: "#94a3b8", fontWeight: 700, marginTop: 4 }}>ACTIVE</div>
                        </div>
                      )}
                      {ghContribTotal != null && (
                        <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 12, padding: "10px 10px", textAlign: "center" }}>
                          <div style={{ fontSize: "1.15rem", fontWeight: 800, color: "#0f172a", lineHeight: 1 }}><CountUp value={ghContribTotal} /></div>
                          <div className="pf-mono" style={{ fontSize: "0.55rem", color: "#94a3b8", fontWeight: 700, marginTop: 4 }}>CONTRIBUTIONS</div>
                        </div>
                      )}
                      {ghFollowers != null && (
                        <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 12, padding: "10px 10px", textAlign: "center" }}>
                          <div style={{ fontSize: "1.15rem", fontWeight: 800, color: "#0f172a", lineHeight: 1 }}><CountUp value={ghFollowers} /></div>
                          <div className="pf-mono" style={{ fontSize: "0.55rem", color: "#94a3b8", fontWeight: 700, marginTop: 4 }}>FOLLOWERS</div>
                        </div>
                      )}
                      {!hasContributions && ghFollowing != null && (
                        <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 12, padding: "10px 10px", textAlign: "center" }}>
                          <div style={{ fontSize: "1.15rem", fontWeight: 800, color: "#0f172a", lineHeight: 1 }}><CountUp value={ghFollowing} /></div>
                          <div className="pf-mono" style={{ fontSize: "0.55rem", color: "#94a3b8", fontWeight: 700, marginTop: 4 }}>FOLLOWING</div>
                        </div>
                      )}
                    </div>
                    {v.github.topLanguages.length > 0 && (
                      <div>
                        <div className="pf-mono" style={{ fontSize: "0.55rem", color: "#94a3b8", fontWeight: 700, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>Languages</div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                          {v.github.topLanguages.slice(0, 6).map((lang) => (
                            <span key={lang} style={{ background: "#f1f5f9", border: "1px solid #e2e8f0", color: "#475569", fontSize: "0.62rem", fontWeight: 700, padding: "3px 8px", borderRadius: 99 }} className="pf-mono">
                              {lang}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {hasContributions && contributions && (
                  <div className={card_}>
                    <div className={`${label_} pf-mono`}>
                      <span>CONTRIBUTION ACTIVITY</span>
                      {contributions.year ? <span>{contributions.year}</span> : null}
                    </div>
                    <ContributionHeatmap
                      levels={contributions.levels}
                      year={contributions.year}
                      total={contributions.total}
                      avgPerDay={contributions.avg_per_day}
                    />
                  </div>
                )}
              </div>
            )}

            {/* ── POSTS & WRITING ── */}
            {v.writing.length > 0 && (
              <div className="pf-span-12 pf-posts" style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 20, padding: "20px 24px" }}>
                <div className="pf-mono flex justify-between items-center mb-4" style={{ fontSize: "0.65rem" }}>
                  <span style={{ color: "#6b63ff", fontWeight: 700 }}>┌ {v.writing.every((w) => ["x", "twitter", "linkedin"].includes(w.platform.toLowerCase())) ? "POSTS & WRITING" : "RECENT WRITING"}</span>
                  <span style={{ background: "#e0e7ff", color: "#4f46e5", padding: "3px 10px", borderRadius: 99, fontWeight: 700 }}>
                    {v.writing.length} ARCHIVED ┐
                  </span>
                </div>
                <AutoScroll rowHeight={POST_ROW_H + POST_GAP} gap={0} visible={VSCROLL_VISIBLE} secondsPerRow={VSCROLL_SECS_PER_ROW}>
                  {v.writing.slice(0, 10).map((post, idx) => {
                    const style = POST_STYLES[idx % POST_STYLES.length];
                    const platform = post.platform.toLowerCase();
                    const isX = ["x", "twitter"].includes(platform);
                    const isLinkedin = platform === "linkedin";
                    const url = safeUrl(post.url);
                    return (
                      <div
                        key={`${post.platform}-${idx}`}
                        className={`pf-vrow pf-vrow-post p-3.5 rounded-2xl border ${style.card}`}
                        style={{ marginBottom: POST_GAP }}
                      >
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-2">
                            <span className={`px-2 py-0.5 rounded font-mono text-[9px] font-semibold flex items-center gap-1 ${style.badge}`}>
                              {isX ? <XGlyph size={10} /> : isLinkedin ? <LinkedinGlyph size={10} /> : null}
                              {isX ? "X" : isLinkedin ? "LinkedIn" : POST_PLATFORM_LABEL[platform] ?? post.platform}
                            </span>
                            <span className={`font-mono text-[10px] font-medium ${style.meta}`}>{post.posted_at}</span>
                          </div>
                          {url && <a href={url} target="_blank" rel="noreferrer" className={`font-mono text-xs ${style.link}`}>↗</a>}
                        </div>
                        <p className={`pf-post-excerpt ${style.text}`}>
                          &ldquo;{post.excerpt}&rdquo;
                        </p>
                      </div>
                    );
                  })}
                </AutoScroll>
              </div>
            )}

            {/* ── WORK: a design portfolio's project covers ── */}
            <WorkGallery items={card.work_gallery ?? []} safeUrl={safeUrl} />

            {/* ── PROJECTS + SKILLS ── */}
            {(v.projects.length > 0 || skills.length > 0) && (
              <div className="pf-span-12 pf-proj-row">

                  {v.projects.length > 0 && (
                    <ProjectsCard
                      projects={v.projects}
                      githubUrl={githubUrl}
                      cardClass={card_}
                      labelClass={label_}
                      pillClass={pill_}
                    />
                  )}

                  {skills.length > 0 && (
                    <div className={`${card_} tc`} style={{ justifyContent: "flex-start" }}>
                      <div className={`${label_} pf-mono`}>
                        <span>┌ SKILL MATRIX</span>
                        <span className={`${pill_} text-indigo-600 bg-indigo-50 border-indigo-200`}>{skills.length} TRACKED ┐</span>
                      </div>
                      <SkillMatrix skills={skills} embedded />
                    </div>
                  )}
              </div>
            )}

            {/* ── EXPLORE FOOTER ── */}
            <div className="pf-span-12 pf-cta" style={{ position: "relative", overflow: "hidden", background: "linear-gradient(120deg, #1e1b4b 0%, #312e81 45%, #4f46e5 100%)", borderRadius: 20, padding: "28px 32px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24, flexWrap: "wrap" }}>
              <div style={{ position: "absolute", right: -40, top: -50, width: 180, height: 180, borderRadius: "50%", background: "rgba(255,255,255,0.08)", pointerEvents: "none" }} />
              <div style={{ position: "relative", display: "flex", gap: 16, alignItems: "center", minWidth: 0 }}>
                <div style={{ width: 48, height: 48, background: "rgba(255,255,255,0.12)", border: "1px solid rgba(255,255,255,0.2)", borderRadius: 14, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, color: "#fff" }}>
                  <Search size={20} />
                </div>
                <div style={{ minWidth: 0 }}>
                  <div className="pf-mono mb-1" style={{ fontSize: "0.62rem", color: "#c7d2fe", fontWeight: 700, letterSpacing: "0.08em" }}>ZYND DIRECTORY</div>
                  <h3 style={{ fontSize: "1.25rem", color: "#fff", fontWeight: 800, margin: 0, lineHeight: 1.25 }}>
                    Find people who share {firstName}&apos;s stack
                  </h3>
                  {skills.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
                      {skills.slice(0, 4).map((s) => (
                        <Link
                          key={s.name}
                          href={`/search?skills=${encodeURIComponent(s.name)}`}
                          className="pf-mono"
                          style={{ fontSize: "0.62rem", fontWeight: 700, color: "#e0e7ff", background: "rgba(255,255,255,0.12)", border: "1px solid rgba(255,255,255,0.18)", borderRadius: 99, padding: "3px 10px", textDecoration: "none" }}
                        >
                          {s.name}
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <Link
                href={skills.length > 0 ? `/search?skills=${skills.slice(0, 3).map((s) => encodeURIComponent(s.name)).join(",")}` : "/directory"}
                style={{ position: "relative", padding: "12px 22px", borderRadius: 99, border: "none", background: "#fff", fontWeight: 800, fontSize: "0.78rem", color: "#312e81", cursor: "pointer", textDecoration: "none", whiteSpace: "nowrap", display: "inline-flex", alignItems: "center", gap: 8, flexShrink: 0 }}
              >
                <Search size={14} /> Find similar profiles
              </Link>
            </div>

          </div>{/* end grid */}

          {/* ── FOOTER ── */}
          <footer className="pf-footer mt-10 pt-6 border-t border-gray-200 flex flex-wrap items-center justify-between gap-4 pf-mono" style={{ fontSize: "0.65rem", color: "#94a3b8" }}>
            <div className="flex items-center gap-2">
              <span style={{ fontWeight: 700, color: "#0f172a" }}>ZYND.AI</span>
              <span>•</span>
              <span>One living profile · synced from LinkedIn, GitHub &amp; AI tools</span>
            </div>
            <div className="pf-footer-links flex flex-wrap items-center gap-3">
              <div className="pf-permalink-badge flex items-center gap-2 px-3 py-1.5 rounded-xl bg-gray-50 border border-gray-200">
                <span className="pf-permalink-text" style={{ color: "#0f172a", fontWeight: 600 }}>{permalink}</span>
                <CopyPermalinkIcon
                  url={withShareRef(`https://${permalink}`, card.handle ?? card.id)}
                  handle={card.handle ?? card.id}
                />
              </div>
              <Link href="/directory" className="hover:text-slate-800">DIRECTORY</Link>
              {claimed && <a href={`/p/${card.handle ?? card.id}/data.json`} className="hover:text-slate-800">FOR AI</a>}
              <Link href="/create" className="hover:text-slate-800">CREATE</Link>
            </div>
          </footer>

        </div>
      </div>

      {claimed && (
        <ProfileChatWidget
          handle={card.handle ?? card.id}
          personName={identity.name}
          prompts={chatPrompts}
          bookingLinks={bookingLinks}
        />
      )}
    </>
  );
}
