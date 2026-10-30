/** Pure helpers for the create page: no React, no fetching, so node's test
 *  runner can load this file as it is (it imports types only). */
import type { AgentProfileCard, BuildStage, Project, SourceStatus, WorkItem, WritingSample } from "@/lib/cards";

export type UrlKind = "github" | "x" | "linkedin" | "writing" | "portfolio" | "website";

/** Newsletter / blog hosts and design-portfolio hosts: the same lists as scraping/sites.py in cards-api. */
const WRITING_HOSTS = ["substack.com", "medium.com", "dev.to", "hashnode.dev", "beehiiv.com", "ghost.io", "wordpress.com", "blogspot.com", "bearblog.dev", "mirror.xyz"];
const PORTFOLIO_HOSTS = ["behance.net", "dribbble.com"];

const onHost = (host: string, domain: string) => host === domain || host.endsWith(`.${domain}`);

export function detectKind(url: string): UrlKind {
  try {
    const host = new URL(url).hostname.toLowerCase().replace(/^www\./, "");
    if (onHost(host, "github.com")) return "github";
    if (host === "x.com" || onHost(host, "twitter.com")) return "x";
    if (onHost(host, "linkedin.com")) return "linkedin";
    if (WRITING_HOSTS.some((d) => onHost(host, d))) return "writing";
    if (PORTFOLIO_HOSTS.some((d) => onHost(host, d))) return "portfolio";
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

/** One tap to start a link; newsletters and portfolios are pasted whole, since each lives on its own address. */
export const QUICK_ADD: { kind: UrlKind; prefix: string }[] = [
  { kind: "linkedin", prefix: "linkedin.com/in/" },
  { kind: "github", prefix: "github.com/" },
  { kind: "x", prefix: "x.com/" },
];

/** The box holds only a quick-add prefix: the person tapped it and has not typed their name yet. */
export function isBarePrefix(raw: string): boolean {
  const value = raw.trim().toLowerCase().replace(/^https?:\/\//, "").replace(/^www\./, "");
  return QUICK_ADD.some(({ prefix }) => value === prefix || `${value}/` === prefix);
}

const HANDLE_HOSTS = ["github.com", "x.com", "twitter.com", "linkedin.com", "behance.net", "dribbble.com"];
/** LinkedIn puts the name one level down: /in/<name>, /company/<name>. */
const LINKEDIN_SECTIONS = ["in", "company", "school", "pub"];

/** A pasted link as the URL we send, or what is wrong with it. */
export function normalizeUrl(raw: string): { url: string } | { error: string } | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const url = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  try {
    const u = new URL(url);
    const host = u.hostname.toLowerCase().replace(/^www\./, "");
    const [first = "", second = ""] = u.pathname.split("/").filter(Boolean);
    const section = host === "linkedin.com" && LINKEDIN_SECTIONS.includes(first.toLowerCase()) ? first : "";
    if (HANDLE_HOSTS.includes(host) && !(section ? second : first)) {
      return { error: `Include your username, e.g. ${host}/${section ? `${section}/` : ""}yourusername` };
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
const IDENTITY_ORDER: UrlKind[] = ["linkedin", "x", "github", "portfolio", "writing", "website"];
const HEADLINE_ORDER: UrlKind[] = ["linkedin", "github", "x", "portfolio", "writing", "website"];
const BIO_ORDER: UrlKind[] = ["linkedin", "x", "github", "portfolio", "writing", "website"];
const POST_ORDER: UrlKind[] = ["linkedin", "x", "writing"];
const POSTS_SHOWN = 3;
const IMAGES_SHOWN = 4;

export interface LiveIdentity {
  name: string;
  headline: string;
  location: string;
  avatar: string;
  bio: string;
  facts: string[];
  posts: string[];
  /** Project covers read from a design portfolio. */
  images: string[];
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
    images: done.flatMap((s) => s.preview.images ?? []).slice(0, IMAGES_SHOWN),
  };
}

/** Whether two builds read the same links, in any order. */
export function sameUrls(a: readonly string[], b: readonly string[]): boolean {
  const set = new Set(a);
  return set.size === new Set(b).size && b.every((u) => set.has(u));
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

/**
 * What the person has changed by hand. Layered over the newest build, so a rebuild never undoes it.
 * Links and skills are kept as changes, not copies: a copy of the old build's list would hide
 * whatever a rebuild adds (a new X link, the skills a new GitHub brings).
 */
export interface DraftEdits {
  name?: string;
  headline?: string;
  summary?: string;
  citation?: string;
  /** `null` is a choice too: the classic look. */
  edition?: AgentProfileCard["identity"]["edition"];
  /** Only the links the person changed, by key; "" removes that link. */
  links?: Record<string, string>;
  skillsAdded?: AgentProfileCard["skills"];
  /** Lower-cased names of the skills the person removed. */
  skillsRemoved?: string[];
}

export function removeLink(edits: DraftEdits, key: string): DraftEdits {
  return { ...edits, links: { ...edits.links, [key]: "" } };
}

export function addSkills(edits: DraftEdits, names: string[]): DraftEdits {
  const added = [...(edits.skillsAdded ?? [])];
  let removed = edits.skillsRemoved ?? [];
  for (const name of names) {
    const lower = name.toLowerCase();
    removed = removed.filter((r) => r !== lower);
    if (!added.some((s) => s.name.toLowerCase() === lower)) added.push({ name, level: "intermediate", evidence_count: 0 });
  }
  return { ...edits, skillsAdded: added, skillsRemoved: removed };
}

export function removeSkill(edits: DraftEdits, name: string): DraftEdits {
  const lower = name.toLowerCase();
  const removed = edits.skillsRemoved ?? [];
  return {
    ...edits,
    skillsAdded: (edits.skillsAdded ?? []).filter((s) => s.name.toLowerCase() !== lower),
    skillsRemoved: removed.includes(lower) ? removed : [...removed, lower],
  };
}

export function applyEdits(card: AgentProfileCard, edits: DraftEdits): AgentProfileCard {
  const identity = { ...card.identity, links: { ...card.identity.links, ...edits.links } };
  if (edits.name !== undefined) identity.name = edits.name;
  if (edits.headline !== undefined) identity.headline = edits.headline;
  if (edits.edition !== undefined) identity.edition = edits.edition;

  const removed = new Set(edits.skillsRemoved);
  const kept = card.skills.filter((s) => !removed.has(s.name.toLowerCase()));
  const have = new Set(kept.map((s) => s.name.toLowerCase()));
  const added = (edits.skillsAdded ?? []).filter((s) => !have.has(s.name.toLowerCase()));
  return {
    ...card,
    identity,
    summary: edits.summary ?? card.summary,
    citation_snippet: edits.citation ?? card.citation_snippet,
    skills: [...kept, ...added],
  };
}

/** The four topic answers, keyed by the card field each one is stored in. */
export interface TopicAnswers {
  working_on: string[];
  can_help_with: string[];
  connect_with: string[];
  love_talking_about: string[];
}

// What a removed row is remembered by. Content, not list position: a rebuild can reorder,
// add or drop rows, and a position would then hide a different one and publish the removed one.
export const projectKey = (p: Pick<Project, "url" | "name">) => `project:${p.url || p.name}`;
export const sampleKey = (w: Pick<WritingSample, "url" | "excerpt">) => `sample:${w.url || w.excerpt}`;
export const workKey = (w: Pick<WorkItem, "url" | "image_url">) => `work:${w.url || w.image_url}`;

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
  // connect_with is saved on the card as-is and left out of searchable_facts: it says who the owner
  // wants to meet, and search read it as who the owner is.
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
    projects: card.projects.filter((p) => !excluded.has(projectKey(p))),
    writing_samples: card.writing_samples.filter((w) => !excluded.has(sampleKey(w))),
    work_gallery: (card.work_gallery ?? []).filter((w) => !excluded.has(workKey(w))),
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
