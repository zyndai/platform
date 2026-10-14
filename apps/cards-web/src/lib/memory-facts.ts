export type MemoryFact = {
  predicate: string;
  object: string;
  confidence?: number;
  source?: string;
  approved_at?: string;
  /** Coarse origin: you | agent | profile | chat | import | inferred. */
  provenance?: string;
};

export const MEMORY_GROUPS: Record<string, { label: string; icon: string }> = {
  is_building: { label: "Currently building", icon: "⚙️" },
  is_working_on: { label: "Working on", icon: "⚙️" },
  is_creating: { label: "Creating", icon: "✨" },
  intends_to: { label: "Planning", icon: "🎯" },
  is_learning: { label: "Learning", icon: "📚" },
  is_seeking: { label: "Seeking", icon: "🤝" },
  open_to: { label: "Open to", icon: "🤝" },
  has_expertise_in: { label: "Expert in", icon: "🧠" },
  has_skill: { label: "Skilled in", icon: "🛠️" },
  uses_tool: { label: "Tools I use", icon: "🧰" },
  is_affiliated_with: { label: "Works at", icon: "🏢" },
  is_located_in: { label: "Based in", icon: "📍" },
};

export const MEMORY_GROUP_ORDER = [
  "is_building",
  "is_working_on",
  "is_creating",
  "intends_to",
  "is_learning",
  "is_seeking",
  "open_to",
  "has_expertise_in",
  "has_skill",
  "uses_tool",
  "is_affiliated_with",
  "is_located_in",
];

const ENUM_LABELS: Record<string, string> = {
  co_founder: "a co-founder",
  technical_feedback: "technical feedback",
  early_users: "early users",
  mentoring: "mentoring",
  being_mentored: "being mentored",
  peer_review: "peer reviews",
  collaboration: "collaboration",
  investment: "investment",
  community: "community",
  coffee_chat: "coffee chats",
  mentoring_others: "mentoring others",
  early_user_testing: "early user testing",
};

const PUBLIC_FAMILY: Record<string, string> = {
  has_skill: "has_expertise_in",
  is_creating: "is_building",
  intends_to: "is_building",
  is_responsible_for: "is_building",
};

export function memoryFactFamily(predicate: string): string {
  return PUBLIC_FAMILY[predicate] ?? predicate;
}

export function memoryFactKey(predicate: string, object: string): string {
  return `${memoryFactFamily(predicate)}|${object.trim().toLowerCase()}`;
}

/** The fact alone, for use under its group heading (the heading already says "Expert in"). */
export function factObjectLabel(fact: Pick<MemoryFact, "predicate" | "object">): string {
  const raw = ENUM_LABELS[fact.object] ?? fact.object.trim();
  return fact.predicate === "is_building" ? raw.replace(/^building\s+/i, "") : raw;
}

export function factLabel(fact: Pick<MemoryFact, "predicate" | "object">): string {
  const raw = ENUM_LABELS[fact.object] ?? fact.object.trim();
  const group = MEMORY_GROUPS[fact.predicate];
  if (fact.predicate === "is_building") return raw.replace(/^building\s+/i, "");
  if (group) return `${group.label}: ${raw}`;
  return raw;
}

export type MemoryGroup = {
  key: string;
  label: string;
  icon: string;
  items: { text: string; object: string }[];
};

export function groupMemoryFacts(facts: MemoryFact[]): MemoryGroup[] {
  const seen = new Set<string>();
  const byPredicate = new Map<string, { text: string; object: string }[]>();
  for (const fact of facts) {
    const predicate = fact.predicate;
    const object = fact.object.trim();
    const family = memoryFactFamily(predicate);
    if (!object || !MEMORY_GROUPS[family]) continue;
    const dedupeKey = memoryFactKey(predicate, object);
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);
    const list = byPredicate.get(family) ?? [];
    list.push({ text: factLabel({ predicate: family, object }), object });
    byPredicate.set(family, list);
  }
  return MEMORY_GROUP_ORDER.filter((key) => byPredicate.has(key)).map((key) => ({
    key,
    label: MEMORY_GROUPS[key].label,
    icon: MEMORY_GROUPS[key].icon,
    items: byPredicate.get(key) ?? [],
  }));
}

/** Plain-words origin of a fact, for the editor chip. */
export const PROVENANCE_LABELS: Record<string, string> = {
  you: "You added this",
  agent: "Reported by your coding agent",
  profile: "From your profile import",
  chat: "Noticed in your AI chats",
  import: "From a memory import",
  inferred: "Inferred",
};

/** Owner-only extras for one fact, keyed by memoryFactKey. Evidence is the person's own
 *  sentence behind the fact and never appears on the public card. */
export type OwnerFactDetail = { provenance?: string; evidence?: string | null };

export type OwnerFactItem = {
  key: string;
  text: string;
  provenance?: string;
  provenanceLabel?: string;
  evidence?: string;
};

export type OwnerFactGroup = {
  key: string;
  label: string;
  icon: string;
  items: OwnerFactItem[];
};

const FREE_TEXT_KEYS = ["content", "value", "text", "description", "fact", "summary"];

/** Group the owner's public facts by card section, deduped, with origin and evidence.
 *  Every fact it returns is one the editor shows, so the editor's count is the sum of
 *  the groups and can never disagree with the list. Free-text facts from an older
 *  memory import (no predicate) go in a trailing "Notes" group. */
export function ownerFactGroups(
  facts: Array<Record<string, unknown>>,
  details: Record<string, OwnerFactDetail> = {},
): OwnerFactGroup[] {
  const seen = new Set<string>();
  const byFamily = new Map<string, OwnerFactItem[]>();
  const notes: OwnerFactItem[] = [];

  for (const fact of facts) {
    const predicate = typeof fact.predicate === "string" ? fact.predicate : "";
    const object = typeof fact.object === "string" ? fact.object.trim() : "";
    if (predicate && object) {
      const family = memoryFactFamily(predicate);
      if (!MEMORY_GROUPS[family]) continue;
      const key = memoryFactKey(predicate, object);
      if (seen.has(key)) continue;
      seen.add(key);
      const detail = details[key] ?? {};
      const provenance =
        detail.provenance ?? (typeof fact.provenance === "string" ? fact.provenance : undefined);
      const list = byFamily.get(family) ?? [];
      list.push({
        key,
        text: factObjectLabel({ predicate: family, object }),
        provenance,
        provenanceLabel: provenance ? PROVENANCE_LABELS[provenance] : undefined,
        evidence: detail.evidence ?? undefined,
      });
      byFamily.set(family, list);
      continue;
    }
    for (const k of FREE_TEXT_KEYS) {
      const value = fact[k];
      if (typeof value === "string" && value.trim()) {
        const text = value.trim();
        const key = `note|${text.toLowerCase()}`;
        if (!seen.has(key)) {
          seen.add(key);
          notes.push({ key, text });
        }
        break;
      }
    }
  }

  const groups: OwnerFactGroup[] = MEMORY_GROUP_ORDER.filter((k) => byFamily.has(k)).map((k) => ({
    key: k,
    label: MEMORY_GROUPS[k].label,
    icon: MEMORY_GROUPS[k].icon,
    items: byFamily.get(k) ?? [],
  }));
  if (notes.length) groups.push({ key: "notes", label: "Notes", icon: "📝", items: notes });
  return groups;
}

export function ownerFactCount(groups: OwnerFactGroup[]): number {
  return groups.reduce((n, g) => n + g.items.length, 0);
}
