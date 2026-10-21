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
  is_founder_of: { label: "Founded", icon: "🏢" },
  has_experience_in: { label: "Experience", icon: "📋" },
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
  "is_founder_of",
  "has_experience_in",
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

/** Which card group a predicate is shown under. */
export function memoryFactFamily(predicate: string): string {
  return PUBLIC_FAMILY[predicate] ?? predicate;
}

// ── De-duplication across predicates ───────────────────────────────────────────────
// Rows written before the Memory write path was unified can hold the same thing under
// several predicates ("Skilled in JavaScript" and "Tools I use: javascript"). They are
// de-duplicated here for display only (nothing is changed in memory) and the stronger
// predicate wins. This is separate from the display family above: a tool still shows under
// "Tools I use" unless the same thing is also a skill or expertise.

const TECH_PREDICATES = new Set(["has_expertise_in", "has_skill", "uses_tool"]);

/** Higher wins when one thing appears under several predicates. */
const DEDUPE_RANK: Record<string, number> = {
  has_expertise_in: 4,
  has_skill: 3,
  uses_tool: 2,
  is_learning: 1,
};

// Mirrors services/memory/app/services/canonical.py for the common names. A safety net,
// not the source of truth: unknown names simply are not folded.
const TECH_ALIASES: Record<string, string> = {
  js: "javascript", ts: "typescript", py: "python", python3: "python", golang: "go",
  node: "node.js", nodejs: "node.js", "node js": "node.js", nextjs: "next.js", next: "next.js",
  reactjs: "react", "react.js": "react", vuejs: "vue", "vue.js": "vue", postgres: "postgresql",
  psql: "postgresql", mongo: "mongodb", k8s: "kubernetes", gcp: "google cloud", cpp: "c++",
  csharp: "c#", tailwind: "tailwind css", vscode: "vs code", "visual studio code": "vs code",
};
const KNOWN_TECH = new Set([
  "javascript", "typescript", "python", "go", "rust", "java", "kotlin", "swift", "c", "c++", "c#",
  "ruby", "php", "scala", "elixir", "haskell", "dart", "sql", "html", "css", "bash",
  "react", "next.js", "vue", "nuxt", "angular", "svelte", "node.js", "deno", "bun", "express",
  "nestjs", "django", "flask", "fastapi", "ruby on rails", "laravel", "spring", "tensorflow",
  "pytorch", "pandas", "numpy", "langchain", "tailwind css", "flutter", "react native",
  "docker", "kubernetes", "terraform", "aws", "google cloud", "azure", "vercel", "supabase",
  "firebase", "postgresql", "mysql", "mongodb", "redis", "sqlite", "git", "github", "figma",
  "notion", "cursor", "vs code", "claude code", "openai", "linux",
]);

function canonicalTech(object: string): string {
  const folded = object.trim().toLowerCase().replace(/\s+/g, " ");
  const direct = TECH_ALIASES[folded] ?? (KNOWN_TECH.has(folded) ? folded : undefined);
  if (direct) return direct;
  // "Python 3.12" -> "python", but only when what is left is a technology we know:
  // "Skill 2" or "Phase 2" must stay as written.
  const stripped = folded.replace(/\s+v?\d+(\.\d+)*(\.x)?$/, "");
  const base = TECH_ALIASES[stripped] ?? (KNOWN_TECH.has(stripped) ? stripped : undefined);
  return base ?? folded;
}

function isKnownTech(object: string): boolean {
  return KNOWN_TECH.has(canonicalTech(object));
}

function dedupeFamily(predicate: string, object: string): string {
  if (TECH_PREDICATES.has(predicate)) return "tech";
  if (predicate === "is_learning" && isKnownTech(object)) return "tech";
  return memoryFactFamily(predicate);
}

export function memoryFactKey(predicate: string, object: string): string {
  const family = dedupeFamily(predicate, object);
  const name = family === "tech" ? canonicalTech(object) : object.trim().toLowerCase();
  return `${family}|${name}`;
}

/** Index of the fact to show for each distinct thing: the strongest predicate, first on a tie. */
function strongestByKey(facts: Array<{ predicate: string; object: string }>): Map<string, number> {
  const best = new Map<string, number>();
  facts.forEach((fact, index) => {
    if (!fact.predicate || !fact.object?.trim()) return;
    const key = memoryFactKey(fact.predicate, fact.object);
    const held = best.get(key);
    if (held === undefined || (DEDUPE_RANK[fact.predicate] ?? 0) > (DEDUPE_RANK[facts[held].predicate] ?? 0)) {
      best.set(key, index);
    }
  });
  return best;
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
  const best = strongestByKey(facts);
  const byPredicate = new Map<string, { text: string; object: string }[]>();
  for (const [index, fact] of facts.entries()) {
    const predicate = fact.predicate;
    const object = fact.object.trim();
    const family = memoryFactFamily(predicate);
    if (!object || !MEMORY_GROUPS[family]) continue;
    if (best.get(memoryFactKey(predicate, object)) !== index) continue;
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
  const best = strongestByKey(
    facts.map((fact) => ({
      predicate: typeof fact.predicate === "string" ? fact.predicate : "",
      object: typeof fact.object === "string" ? fact.object : "",
    })),
  );

  for (const [index, fact] of facts.entries()) {
    const predicate = typeof fact.predicate === "string" ? fact.predicate : "";
    const object = typeof fact.object === "string" ? fact.object.trim() : "";
    if (predicate && object) {
      const family = memoryFactFamily(predicate);
      if (!MEMORY_GROUPS[family]) continue;
      const key = memoryFactKey(predicate, object);
      if (best.get(key) !== index) continue;
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
