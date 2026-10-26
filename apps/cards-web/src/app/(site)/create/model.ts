/** Pure helpers for the create page: no React, no fetching, so node's test
 *  runner can load this file as it is (it imports types only). */
import type { AgentProfileCard, BuildStage, SourceStatus } from "@/lib/cards";

export type UrlKind = "github" | "x" | "linkedin" | "website";

export function detectKind(url: string): UrlKind {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host === "github.com" || host.endsWith(".github.com")) return "github";
    if (host === "x.com" || host === "twitter.com" || host.endsWith(".twitter.com")) return "x";
    if (host === "linkedin.com" || host.endsWith(".linkedin.com")) return "linkedin";
  } catch { /* not a URL: treat as a website */ }
  return "website";
}

export function shortenUrl(url: string): string {
  try {
    const u = new URL(url);
    return (u.hostname.replace(/^www\./, "") + u.pathname).replace(/\/$/, "").slice(0, 38);
  } catch {
    return url.slice(0, 38);
  }
}

/** A pasted link as the URL we send, or what is wrong with it. */
export function normalizeUrl(raw: string): { url: string } | { error: string } | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const url = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  try {
    const u = new URL(url);
    const host = u.hostname.toLowerCase().replace(/^www\./, "");
    const needsHandle = host === "github.com" || host === "x.com" || host === "twitter.com" || host === "linkedin.com";
    if (needsHandle && !u.pathname.replace(/^\//, "").split("/")[0]) {
      return { error: `Include your username, e.g. ${host}/yourusername` };
    }
    if (!host.includes(".")) return { error: "That doesn't look like a link." };
  } catch {
    return { error: "That doesn't look like a link." };
  }
  return { url };
}

/** What is allowed in a custom profile slug, as typed. */
export function slugifyHandle(raw: string): string {
  return raw.toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 30);
}

/** A custom profile slug as the API accepts it, or "" when too short to try. */
export function cleanHandle(raw: string): string {
  const slug = slugifyHandle(raw);
  return slug.length >= 2 ? slug : "";
}

// ─── what the sources have revealed so far ───────────────────────────────────

/** Whose word wins for each field; photos follow the API's LinkedIn > X > GitHub rule. */
const IDENTITY_ORDER: UrlKind[] = ["linkedin", "x", "github", "website"];
const HEADLINE_ORDER: UrlKind[] = ["linkedin", "github", "x", "website"];
const BIO_ORDER: UrlKind[] = ["linkedin", "x", "github", "website"];
const POST_ORDER: UrlKind[] = ["linkedin", "x"];
const POSTS_SHOWN = 3;

export interface LiveIdentity {
  name: string;
  headline: string;
  location: string;
  avatar: string;
  bio: string;
  facts: string[];
  posts: string[];
}

function pick(sources: SourceStatus[], order: UrlKind[], field: "name" | "headline" | "location" | "avatar" | "bio"): string {
  for (const kind of order) {
    for (const s of sources) {
      const value = s.state === "done" && detectKind(s.url) === kind ? s.preview[field] : "";
      if (value) return value;
    }
  }
  return "";
}

/** One identity out of every source that has finished, before the card is written. */
export function liveIdentity(sources: SourceStatus[]): LiveIdentity {
  const done = sources.filter((s) => s.state === "done");
  const posts = POST_ORDER.flatMap((kind) =>
    done.filter((s) => detectKind(s.url) === kind).flatMap((s) => s.preview.posts ?? []),
  );
  return {
    name: pick(done, IDENTITY_ORDER, "name"),
    headline: pick(done, HEADLINE_ORDER, "headline"),
    location: pick(done, IDENTITY_ORDER, "location"),
    avatar: pick(done, IDENTITY_ORDER, "avatar"),
    bio: pick(done, BIO_ORDER, "bio"),
    facts: done.flatMap((s) => s.preview.facts ?? []),
    posts: posts.slice(0, POSTS_SHOWN),
  };
}

/** One line for where the build is. */
export function statusLine(sources: SourceStatus[], stage: BuildStage): string {
  if (stage === "ready") return "Draft ready. Check it over and publish.";
  if (stage === "synthesizing") return "Writing your summary and skills…";
  const reading = sources.filter((s) => s.state === "reading").length;
  if (reading > 1) return `Reading ${reading} sources…`;
  if (reading === 1) return "Reading your profile…";
  return "Starting…";
}

// ─── the draft card ──────────────────────────────────────────────────────────

/** What the person has changed by hand. Layered over the newest build, so a rebuild never undoes it. */
export interface DraftEdits {
  name?: string;
  headline?: string;
  summary?: string;
  citation?: string;
  skills?: AgentProfileCard["skills"];
  /** `null` is a choice too: the classic look. */
  edition?: AgentProfileCard["identity"]["edition"];
  links?: Record<string, string>;
}

export function applyEdits(card: AgentProfileCard, edits: DraftEdits): AgentProfileCard {
  const identity = { ...card.identity };
  if (edits.name !== undefined) identity.name = edits.name;
  if (edits.headline !== undefined) identity.headline = edits.headline;
  if (edits.edition !== undefined) identity.edition = edits.edition;
  if (edits.links !== undefined) identity.links = edits.links;
  return {
    ...card,
    identity,
    summary: edits.summary ?? card.summary,
    citation_snippet: edits.citation ?? card.citation_snippet,
    skills: edits.skills ?? card.skills,
  };
}

/** The four topic answers, keyed by the card field each one is stored in. */
export interface TopicAnswers {
  working_on: string[];
  can_help_with: string[];
  connect_with: string[];
  love_talking_about: string[];
}

export const projectKey = (p: { url?: string }, i: number) => `project:${p.url || i}`;
export const sampleKey = (i: number) => `sample:${i}`;

/** The card as it will be published: the person's answers applied, removed rows dropped. */
export function finalizeCard(
  card: AgentProfileCard,
  answers: TopicAnswers,
  location: string,
  excluded: ReadonlySet<string>,
): AgentProfileCard {
  const name = card.identity.name || "This person";
  const facts = [...card.searchable_facts];
  if (answers.working_on.length) facts.push(`${name} — working on ${answers.working_on.join(", ")} — Zynd`);
  if (answers.connect_with.length) facts.push(`${name} — looking to connect with ${answers.connect_with.join(", ")} — Zynd`);
  if (answers.love_talking_about.length) facts.push(`${name} — loves talking about ${answers.love_talking_about.join(", ")} — Zynd`);

  const have = new Set(card.skills.map((s) => s.name.toLowerCase()));
  const skills = [
    ...card.skills,
    ...answers.can_help_with
      .filter((n) => !have.has(n.toLowerCase()))
      .map((n) => ({ name: n, level: "intermediate", evidence_count: 1 })),
  ];

  return {
    ...card,
    identity: { ...card.identity, location: location.trim() || card.identity.location },
    summary: card.summary || (answers.working_on.length ? `Currently working on: ${answers.working_on.join(", ")}.` : ""),
    // The person's picks are authoritative, an emptied group included: the API
    // only overrides these from answers when they are non-empty.
    working_on: answers.working_on,
    can_help_with: answers.can_help_with,
    connect_with: answers.connect_with,
    love_talking_about: answers.love_talking_about,
    searchable_facts: facts,
    skills,
    projects: card.projects.filter((p, i) => !excluded.has(projectKey(p, i))),
    writing_samples: card.writing_samples.filter((_, i) => !excluded.has(sampleKey(i))),
  };
}

/** What POST /onboard/{job}/publish keeps as the person's stated intent. */
export function buildUserAnswers(
  answers: TopicAnswers,
  location: string,
  calendly: string,
  googleCalendar: string,
): Record<string, string> {
  const out: Record<string, string> = {};
  if (answers.working_on.length) out.working_on = answers.working_on.join(", ");
  if (answers.can_help_with.length) out.can_help = answers.can_help_with.join(", ");
  if (answers.connect_with.length) out.connect_with = answers.connect_with.join(", ");
  if (answers.love_talking_about.length) out.love_talking = answers.love_talking_about.join(", ");
  if (location.trim()) out.location = location.trim();
  if (calendly.trim()) out.calendly_url = calendly.trim();
  if (googleCalendar.trim()) out.google_calendar_url = googleCalendar.trim();
  return out;
}
