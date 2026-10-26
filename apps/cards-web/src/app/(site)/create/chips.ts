/** The one-tap answers on the create page. The same labels are offered to the
 *  LLM in services/cards-api/synthesis/synthesize.py (CHIP_VOCAB), so a
 *  suggestion that reuses one lands pre-selected on the matching chip. */

export type ChipGroupId = "working_on" | "can_help" | "connect_with" | "love_talking";

/** Where the group's answers live on the card. */
export type ChipCardField = "working_on" | "can_help_with" | "connect_with" | "love_talking_about";

export interface ChipGroup {
  id: ChipGroupId;
  field: ChipCardField;
  label: string;
  options: string[];
}

export const CHIP_GROUPS: ChipGroup[] = [
  {
    id: "working_on", field: "working_on",
    label: "What are you working on?",
    options: [
      "Building a startup", "Building with AI", "Open source", "Side project", "Indie hacking",
      "B2B SaaS", "Consumer apps", "Deep tech / research", "Freelancing", "At a company",
      "Doing research", "Grad school", "Writing", "Teaching / mentoring", "Community building",
      "Design / creative work", "Investing", "Job hunting",
    ],
  },
  {
    id: "can_help", field: "can_help_with",
    label: "What can you help people with?",
    options: [
      "Code review", "System design", "ML / AI", "Cloud / infra", "Data / analytics", "Security",
      "Technical interviews", "Hiring", "Career advice", "Fundraising", "Pitching / storytelling",
      "Sales", "Marketing", "Go-to-market", "Design", "Legal / compliance", "Immigration / visas",
      "Public speaking",
    ],
  },
  {
    id: "connect_with", field: "connect_with",
    label: "Who would you like to connect with?",
    options: [
      "Founders", "Investors", "Engineers", "ML Researchers", "Product Managers", "Designers",
      "Operators", "Scientists", "Recruiters", "Mentors", "Potential co-founders", "Customers",
      "Students", "Writers", "DevRel", "Researchers in my field", "Healthcare builders",
      "Robotics people",
    ],
  },
  {
    id: "love_talking", field: "love_talking_about",
    label: "What do you love talking about?",
    options: [
      "AI / ML", "Agentic AI", "Startups", "Developer tools", "Open source", "Web3 / Crypto",
      "Climate tech", "Robotics", "Hardware", "Design", "Research", "SaaS",
      "Engineering culture", "Books", "Philosophy", "Personal finance", "Gaming",
      "History / science",
    ],
  },
];

export type Selections = Record<ChipGroupId, string[]>;

export const emptySelections = (): Selections => ({
  working_on: [], can_help: [], connect_with: [], love_talking: [],
});

/** Add comma-separated typed values, matching a preset label's casing and skipping repeats. */
export function addCustomValues(existing: string[], options: string[], raw: string): string[] {
  const have = new Set(existing.map((s) => s.toLowerCase()));
  const next = [...existing];
  for (const part of raw.split(",")) {
    const value = part.trim();
    const key = value.toLowerCase();
    if (!value || have.has(key)) continue;
    next.push(options.find((o) => o.toLowerCase() === key) ?? value);
    have.add(key);
  }
  return next;
}

/** The same label, whichever way it was cased. */
export const sameLabel = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

export const hasLabel = (list: string[], label: string) => list.some((x) => sameLabel(x, label));
