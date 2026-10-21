/** Public topics are short labels; biography text stays in the biography. */
const PLACEHOLDERS = new Set(["general", "misc", "miscellaneous", "other", "none", "null", "undefined", "unknown", "n/a"]);

export function cleanTopic(value: unknown): string {
  if (typeof value !== "string") return "";
  const text = value.trim().replace(/^["'`]+|["'`]+$/g, "").replace(/\s+/g, " ");
  if (!text || PLACEHOLDERS.has(text.toLowerCase()) || text.length > 100 || text.split(" ").length > 8) return "";
  if (/[!?;\n]|\.\s|https?:\/\/|\b(?:founder of|founded|organized|worked at)\b/i.test(text)) return "";
  return text;
}

export function publicTopics(skills: Array<{ name: string }>, facts: Array<{ type: string; text: string }> = []): string[] {
  const candidates = [...skills.map(s => s.name), ...facts.filter(f => ["has_expertise_in", "has_skill", "is_learning"].includes(f.type)).map(f => f.text)];
  const seen = new Set<string>();
  return candidates.map(cleanTopic).filter(text => {
    const key = text.toLowerCase();
    if (!text || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** Interests are intentionally absent: an interest does not assert active learning. */
export function cardDeclarations(card: {
  working_on?: string[]; can_help_with?: string[]; skills: Array<{ name: string }>;
  identity: { location?: string };
}): Array<{ predicate: string; value: string }> {
  const out: Array<{ predicate: string; value: string }> = [];
  for (const value of (card.working_on ?? []).slice(0, 5)) {
    if (value.trim() && value.trim().length <= 120) out.push({ predicate: "is_building", value: value.trim() });
  }
  const expertise = publicTopics((card.can_help_with ?? []).map(name => ({ name })));
  for (const value of (expertise.length ? expertise : publicTopics(card.skills)).slice(0, 5)) {
    out.push({ predicate: "has_expertise_in", value });
  }
  const location = card.identity.location?.trim();
  if (location) out.push({ predicate: "is_located_in", value: location });
  return out;
}
