/** The one-tap answers on the create page, tailored to the kind of professional.
 *
 *  A marketer should not be offered "Rust" and "CRDTs". The API's synthesis step
 *  decides which persona the evidence points to (services/cards-api/synthesis/
 *  taxonomy.py, which holds this same vocabulary: chips.test.ts fails when the two
 *  drift) and the person can switch it. A suggestion that reuses one of these
 *  labels lands pre-selected on that chip; anything else shows as a custom chip. */

export type ChipGroupId = "working_on" | "can_help" | "connect_with" | "love_talking";

/** Where the group's answers live on the card. */
export type ChipCardField = "working_on" | "can_help_with" | "connect_with" | "love_talking_about";

export interface ChipGroup {
  id: ChipGroupId;
  field: ChipCardField;
  /** The heading on the card. */
  label: string;
  /** Shown while the person is editing the group. */
  tip: string;
}

export const CHIP_GROUPS: ChipGroup[] = [
  {
    id: "working_on", field: "working_on", label: "Working on",
    tip: "Rule: Write for the person who will meet you next, not your whole career history.",
  },
  {
    id: "can_help", field: "can_help_with", label: "Can help with",
    tip: "Be concrete: “pricing a first enterprise deal” beats “business advice”.",
  },
  {
    id: "connect_with", field: "connect_with", label: "Wants to meet",
    tip: "Name who should reach out: roles and stages, not company names.",
  },
  {
    id: "love_talking", field: "love_talking_about", label: "Loves talking about",
    tip: "Pick what you could talk about for an hour.",
  },
];

export type PersonaId =
  | "engineering" | "founder" | "product_design" | "marketing_sales"
  | "creator" | "research" | "investor" | "general";

export const DEFAULT_PERSONA: PersonaId = "general";

export const PERSONAS: { id: PersonaId; label: string }[] = [
  { id: "general", label: "Anyone" },
  { id: "engineering", label: "Engineering & data" },
  { id: "founder", label: "Founders & operators" },
  { id: "product_design", label: "Product & design" },
  { id: "marketing_sales", label: "Marketing & sales" },
  { id: "creator", label: "Writers & creators" },
  { id: "research", label: "Research & academia" },
  { id: "investor", label: "Investing & finance" },
];

export const isPersona = (value: unknown): value is PersonaId => PERSONAS.some((p) => p.id === value);

export const PERSONA_VOCAB: Record<PersonaId, Record<ChipCardField, string[]>> = {
  general: {
    working_on: ["A new venture", "A side project", "My current role", "Freelance work", "Research", "Writing", "Teaching / mentoring", "Community building", "Career change", "Looking for work", "Learning something new", "Investing"],
    can_help_with: ["Career advice", "Introductions", "Mentoring", "Hiring", "Feedback on ideas", "Public speaking", "Writing", "Strategy", "Fundraising", "Project management", "Negotiation", "Networking"],
    connect_with: ["Founders", "Mentors", "Collaborators", "Hiring managers", "Investors", "Customers", "Peers in my field", "Recruiters", "Students", "Advisors", "Potential co-founders", "Speakers / hosts"],
    love_talking_about: ["Startups", "Technology", "Books", "Travel", "Design", "Health", "Personal finance", "Education", "Philosophy", "Sports", "Film / music", "Climate"],
  },
  engineering: {
    working_on: ["Building a startup", "Building with AI", "Open source", "A side project", "Developer tools", "Infrastructure / platform", "Data / ML systems", "Mobile apps", "Security", "Research engineering", "Indie hacking", "At a company"],
    can_help_with: ["Code review", "System design", "ML / AI", "Cloud / infra", "Data / analytics", "Security", "Technical interviews", "Open source", "Architecture", "Performance", "Mobile", "DevOps"],
    connect_with: ["Engineers", "ML researchers", "Founders", "Open-source maintainers", "Potential co-founders", "Engineering managers", "DevRel", "Recruiters", "Investors", "Security folks", "Mentors", "Hardware / robotics people"],
    love_talking_about: ["AI / ML", "Agentic AI", "Developer tools", "Open source", "Distributed systems", "Startups", "Web3 / crypto", "Robotics", "Hardware", "Programming languages", "Engineering culture", "Security"],
  },
  founder: {
    working_on: ["Building a startup", "Raising funding", "Finding first customers", "Scaling a team", "B2B SaaS", "A consumer product", "A marketplace", "Hiring", "Going to market", "Looking for a co-founder", "Exploring ideas", "Running an agency / studio"],
    can_help_with: ["Fundraising", "Pitching / storytelling", "Hiring", "Go-to-market", "Pricing", "First customers", "Team building", "Operations", "Product strategy", "Investor intros", "Company building", "Managing teams"],
    connect_with: ["Investors", "Founders", "Potential co-founders", "Customers", "Operators", "Advisors", "Mentors", "Recruiters", "Partners", "Press", "Engineers", "Designers"],
    love_talking_about: ["Startups", "Fundraising", "Product-market fit", "Hiring", "Leadership", "SaaS", "AI", "Climate tech", "Consumer products", "Sales", "Company culture", "Strategy"],
  },
  product_design: {
    working_on: ["Shipping a product", "Product strategy", "Design systems", "Brand identity", "UX research", "Mobile / app design", "Prototyping", "Design leadership", "Freelance design", "A portfolio refresh", "Zero-to-one products", "Accessibility"],
    can_help_with: ["Product strategy", "UX / UI design", "Design systems", "User research", "Prototyping", "Roadmapping", "Branding", "Portfolio reviews", "Design critique", "Accessibility", "Product discovery", "Career advice"],
    connect_with: ["Designers", "Product managers", "Engineers", "Founders", "Researchers", "Creative directors", "Hiring managers", "Studios / agencies", "Clients", "Mentors", "Illustrators", "Brands"],
    love_talking_about: ["Product design", "UX", "Design systems", "Typography", "Brand", "Prototyping", "AI & design", "Product strategy", "Accessibility", "Illustration", "Motion", "Creative tools"],
  },
  marketing_sales: {
    working_on: ["Brand strategy", "Content marketing", "Growth / demand gen", "Outbound sales", "Partnerships", "Product marketing", "Community & events", "SEO / performance", "Founder-led sales", "A launch", "Communications / PR", "Customer success"],
    can_help_with: ["Brand strategy", "Content strategy", "Positioning / messaging", "Sales", "Go-to-market", "Growth experiments", "SEO", "Email / lifecycle", "Partnerships", "PR / comms", "Social media", "Pricing"],
    connect_with: ["Founders", "Marketers", "Sales leaders", "Clients", "Agencies", "Partners", "Creators", "Journalists", "Product teams", "Investors", "Recruiters", "Community managers"],
    love_talking_about: ["Brand", "Growth", "Content", "Storytelling", "Sales", "AI in marketing", "Social media", "SEO", "Community", "Startups", "Consumer behaviour", "Creator economy"],
  },
  creator: {
    working_on: ["A newsletter", "A book", "A podcast", "Video content", "A course / workshop", "Freelance writing", "Building an audience", "A creative project", "Journalism", "Photography / film", "Music / art", "Community"],
    can_help_with: ["Writing / editing", "Storytelling", "Growing an audience", "Newsletters", "Podcasting", "Video production", "Public speaking", "Interviewing", "Content strategy", "Teaching / workshops", "Publishing", "Social media"],
    connect_with: ["Editors", "Publishers", "Brands", "Other creators", "Podcast hosts", "Founders", "Collaborators", "Journalists", "Sponsors", "Mentors", "Speakers", "Agents"],
    love_talking_about: ["Writing", "Storytelling", "Books", "Creator economy", "Media", "Newsletters", "Podcasts", "Culture", "Film / music", "Philosophy", "Technology", "Education"],
  },
  research: {
    working_on: ["A research paper", "Grad school", "A PhD", "Lab work", "A dataset / benchmark", "Teaching", "Grant writing", "Industry research", "Open science", "Science communication", "A thesis", "A postdoc"],
    can_help_with: ["Research design", "Statistics / methods", "Paper feedback", "Grant writing", "Data analysis", "Academic careers", "Grad school advice", "Peer review", "Science communication", "ML / AI", "Teaching", "Literature reviews"],
    connect_with: ["Researchers in my field", "Collaborators", "Advisors", "Students", "Industry labs", "Funders", "Engineers", "Founders", "Mentors", "Journal editors", "Policy makers", "Conference organizers"],
    love_talking_about: ["My field", "AI / ML", "Science communication", "Open science", "Methods", "Climate", "Healthcare", "Neuroscience", "Philosophy of science", "Education", "History / science", "Policy"],
  },
  investor: {
    working_on: ["Sourcing deals", "Seed investing", "Angel investing", "Portfolio support", "Market research", "Building a fund", "Due diligence", "Public markets", "A venture studio", "Impact investing", "Advising founders", "Building a thesis"],
    can_help_with: ["Fundraising", "Deal structuring", "Valuation", "Due diligence", "Market mapping", "Investor intros", "Portfolio support", "Financial modeling", "Fund operations", "Pitch feedback", "Term sheets", "Market analysis"],
    connect_with: ["Founders", "Co-investors", "LPs", "Operators", "Advisors", "Bankers", "Fund managers", "Researchers", "Recruiters", "Mentors", "Journalists", "Domain experts"],
    love_talking_about: ["Markets", "Venture capital", "Startups", "AI", "Climate tech", "Fintech", "Macro", "Company building", "Emerging markets", "Founder stories", "Valuation", "Personal finance"],
  },
};

/** The preset labels a group offers for a persona. */
export const optionsFor = (persona: PersonaId, group: ChipGroup): string[] => PERSONA_VOCAB[persona][group.field];

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
