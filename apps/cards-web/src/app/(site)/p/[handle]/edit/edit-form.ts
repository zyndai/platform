import type { AgentProfileCard } from "@/lib/cards";
import { readEdition, type CardEdition } from "@/lib/editions";

/** Everything the owner can type on the edit page, in one object. */
export interface EditForm {
  name: string;
  headline: string;
  location: string;
  /** Display only: the photo comes from the linked accounts, never from this form. */
  avatar: string;
  links: [string, string][];
  summary: string;
  availability: string;
  industries: string[];
  workingOn: string[];
  connectWith: string[];
  talkingAbout: string[];
  skills: AgentProfileCard["skills"];
  calendly: string;
  gcal: string;
  /** Limited-edition look; null is the classic card. */
  edition: CardEdition | null;
}

export type SetField = <K extends keyof EditForm>(key: K, value: EditForm[K]) => void;

export type TabKey = "profile" | "interests" | "imported" | "ai";

/** `short` replaces `label` on phones so all four tabs fit without scrolling. */
export const TABS: { key: TabKey; label: string; short: string }[] = [
  { key: "profile", label: "Profile", short: "Profile" },
  { key: "interests", label: "Interests & Skills", short: "Interests" },
  { key: "imported", label: "Imported", short: "Imported" },
  { key: "ai", label: "AI & Memory", short: "AI" },
];

/** Which tab holds each deep-link anchor. Owner home, completeness actions and
 *  notification emails link to /edit#<anchor>, so every old anchor stays here. */
const ANCHOR_TAB: Record<string, TabKey> = {
  identity: "profile", avatar: "profile", presence: "profile", links: "profile", style: "profile",
  summary: "profile", settings: "profile",
  signals: "interests", skills: "interests", beacon: "interests",
  career: "imported", projects: "imported", stats: "imported",
  inbox: "ai", memory: "ai", "connect-mcp": "ai",
};

/** Autosave sections each tab writes, for the "saving" dot on the tab. */
export const TAB_SECTIONS: Partial<Record<TabKey, string[]>> = {
  profile: ["identity", "summary", "settings"],
  interests: ["signals", "skills"],
};

export function tabForHash(hash: string): TabKey {
  if (TABS.some((t) => t.key === hash)) return hash as TabKey;
  return ANCHOR_TAB[hash] ?? "profile";
}

export function withDefaultLinks(entries: [string, string][]): [string, string][] {
  const map = new Map(entries.map(([p, u]) => [p.toLowerCase(), [p, u] as [string, string]]));
  for (const key of ["github", "linkedin", "x", "website"]) {
    if (!map.has(key)) map.set(key, [key, ""]);
  }
  return [...map.values()];
}

export function formFromCard(card: AgentProfileCard): EditForm {
  return {
    name: card.identity.name,
    headline: card.identity.headline,
    location: card.identity.location,
    avatar: card.identity.avatar_url,
    links: withDefaultLinks(Object.entries(card.identity.links ?? {}).map(([p, u]) => [p, u as string])),
    summary: card.summary,
    availability: card.availability,
    industries: card.industries,
    workingOn: card.working_on,
    connectWith: card.connect_with,
    talkingAbout: card.love_talking_about,
    skills: card.skills,
    calendly: card.calendly_url ?? "",
    gcal: card.google_calendar_url ?? "",
    edition: readEdition(card.identity.edition),
  };
}

export function formLinks(form: EditForm): Record<string, string> {
  return Object.fromEntries(form.links.filter(([p, u]) => p.trim() && u.trim()));
}

export function cardFromForm(base: AgentProfileCard, form: EditForm): AgentProfileCard {
  return {
    ...base,
    identity: {
      ...base.identity,
      name: form.name, headline: form.headline, location: form.location,
      links: formLinks(form),
      // Classic cards that never had an edition keep sending the identity they always did.
      ...(form.edition || "edition" in base.identity ? { edition: form.edition } : {}),
    },
    summary: form.summary,
    availability: form.availability,
    industries: form.industries,
    working_on: form.workingOn,
    connect_with: form.connectWith,
    love_talking_about: form.talkingAbout,
    skills: form.skills,
    calendly_url: form.calendly.trim() || null,
    google_calendar_url: form.gcal.trim() || null,
  };
}

export function safeUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const { protocol } = new URL(url);
    return protocol === "http:" || protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}

export function initialsOf(name: string): string {
  return (name || "?").split(/\s+/).map((p) => p[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
}
