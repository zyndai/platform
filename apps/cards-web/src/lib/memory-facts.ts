export type MemoryFact = {
  predicate: string;
  object: string;
  confidence?: number;
  source?: string;
  approved_at?: string;
};

export const MEMORY_GROUPS: Record<string, { label: string; icon: string }> = {
  is_building: { label: "Currently building", icon: "⚙️" },
  is_learning: { label: "Learning", icon: "📚" },
  is_seeking: { label: "Seeking", icon: "🤝" },
  open_to: { label: "Open to", icon: "🤝" },
  has_expertise_in: { label: "Expert in", icon: "🧠" },
  is_affiliated_with: { label: "Works at", icon: "🏢" },
  is_located_in: { label: "Based in", icon: "📍" },
};

export const MEMORY_GROUP_ORDER = [
  "is_building",
  "is_learning",
  "is_seeking",
  "open_to",
  "has_expertise_in",
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

export function factLabel(fact: Pick<MemoryFact, "predicate" | "object">): string {
  const raw = ENUM_LABELS[fact.object] ?? fact.object.trim();
  if (fact.predicate === "is_building") return raw.replace(/^building\s+/i, "");
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
    if (!predicate || !object || !MEMORY_GROUPS[predicate]) continue;
    const dedupeKey = `${predicate}|${object.toLowerCase()}`;
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);
    const list = byPredicate.get(predicate) ?? [];
    list.push({ text: factLabel(fact), object });
    byPredicate.set(predicate, list);
  }
  return MEMORY_GROUP_ORDER.filter((key) => byPredicate.has(key)).map((key) => ({
    key,
    label: MEMORY_GROUPS[key].label,
    icon: MEMORY_GROUPS[key].icon,
    items: byPredicate.get(key) ?? [],
  }));
}
