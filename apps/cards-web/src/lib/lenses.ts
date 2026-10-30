/** Context lenses: the same public card, arranged for one kind of reader
 *  (`/p/<handle>?lens=investors`). A lens only reorders, rings and folds sections
 *  the card already shows, and writes its header line from fields already on the
 *  card, so every lens URL is the same page underneath (it declares the plain card
 *  URL as canonical) and needs no new data or model call. */

export type LensId = "investors" | "hiring" | "clients" | "collaborators";

/** The full-width rows of the profile grid below the identity block, by their
 *  `data-section` attribute in p/[handle]. The identity block (hero, About,
 *  signals) carries none and always stays first. */
export type LensSectionId =
  | "exploring" | "helped" | "beacon" | "experience" | "social"
  | "github" | "writing" | "gallery" | "projects" | "explore";

export interface Lens {
  id: LensId;
  /** "Share for investors" on the owner's picker. */
  audience: string;
  /** "Viewing as an investor" on the card. */
  viewer: string;
  /** Pulled up under the identity block, in this order. */
  lead: LensSectionId[];
  /** A subset of `lead` that gets the accent ring. */
  highlight: LensSectionId[];
  /** Kept on the page but clipped to a preview at the bottom: the reader can
   *  still see the section exists, and the bar links to the full card. */
  fold: LensSectionId[];
  /** "Wants to meet" labels (create/chips.ts PERSONA_VOCAB.connect_with) that
   *  mean the owner is looking for this reader. */
  wants: string[];
}

export const LENSES: Lens[] = [
  {
    id: "investors",
    audience: "investors",
    viewer: "an investor",
    lead: ["projects", "github", "social", "experience"],
    highlight: ["projects", "github"],
    fold: ["gallery"],
    wants: ["Investors", "Co-investors", "Funders"],
  },
  {
    id: "hiring",
    audience: "hiring managers",
    viewer: "a hiring manager",
    lead: ["experience", "projects", "github", "gallery", "writing"],
    highlight: ["experience", "projects"],
    fold: ["exploring"],
    wants: ["Hiring managers", "Recruiters"],
  },
  {
    id: "clients",
    audience: "clients",
    viewer: "a client",
    lead: ["gallery", "helped", "projects", "social", "experience"],
    highlight: ["gallery", "helped"],
    fold: ["github"],
    wants: ["Clients", "Customers", "Brands", "Sponsors"],
  },
  {
    id: "collaborators",
    audience: "collaborators",
    viewer: "a collaborator",
    lead: ["exploring", "projects", "github", "writing", "helped"],
    highlight: ["exploring", "projects"],
    fold: ["experience"],
    wants: ["Collaborators", "Potential co-founders", "Peers in my field", "Researchers in my field", "Other creators"],
  },
];

// Names people are likely to type or that the chip vocabulary uses ("Hires").
const ALIASES: Record<string, LensId> = {
  investor: "investors",
  hire: "hiring",
  hires: "hiring",
  recruiters: "hiring",
  client: "clients",
  customers: "clients",
  collaborator: "collaborators",
};

/** The lens a `?lens=` value names, or null for a plain card. Repeated params
 *  (`?lens=a&lens=b`) arrive as an array; the first one wins. */
export function parseLens(raw: string | string[] | undefined): Lens | null {
  const value = (Array.isArray(raw) ? raw[0] : raw)?.trim().toLowerCase();
  if (!value) return null;
  const id = Object.hasOwn(ALIASES, value) ? ALIASES[value] : value;
  return LENSES.find((lens) => lens.id === id) ?? null;
}

export function lensPath(handle: string, lens: LensId): string {
  return `/p/${encodeURIComponent(handle)}?lens=${lens}`;
}

/** The card fields a lens header reads. */
export interface LensCardFields {
  name: string;
  working_on: string[];
  can_help_with: string[];
  connect_with: string[];
  love_talking_about: string[];
  experience_years: number | null;
}

const MAX_HEADER_ITEMS = 2;

const filled = (items: string[]) => items.map((item) => item.trim()).filter(Boolean);
const list = (items: string[]) => filled(items).slice(0, MAX_HEADER_ITEMS).join(", ");

/** The one-line context under "Viewing as …": whether the owner is looking for
 *  this reader, then the field that reader asks about first. Empty when the card
 *  has none of them, so the bar shows only its title. */
export function lensSummary(lens: Lens, card: LensCardFields): string {
  const firstName = card.name.trim().split(/\s+/)[0];
  const wanted = filled(card.connect_with).find((label) =>
    lens.wants.some((want) => want.toLowerCase() === label.toLowerCase()));
  const parts: string[] = [];
  if (wanted) parts.push(`${firstName ? `${firstName} wants` : "Wants"} to meet ${wanted.toLowerCase()}.`);

  const working = list(card.working_on);
  const help = list(card.can_help_with);
  const talk = list(card.love_talking_about);
  const years = card.experience_years;
  if (lens.id === "investors" && working) parts.push(`Working on ${working}.`);
  if (lens.id === "hiring") {
    if (years != null && years > 0) parts.push(`${years} ${years === 1 ? "year" : "years"} of experience.`);
    else if (help) parts.push(`Can help with ${help}.`);
  }
  if (lens.id === "clients" && help) parts.push(`Can help with ${help}.`);
  if (lens.id === "collaborators" && (talk || working)) {
    parts.push(talk ? `Loves talking about ${talk}.` : `Working on ${working}.`);
  }
  return parts.join(" ");
}

const LEAD_ORDER_START = 1;

/** The stylesheet that arranges the grid for a lens. CSS `order` instead of
 *  re-rendering the sections in a new order keeps the page's JSX (and every
 *  other branch's edits to it) untouched; it is safe here because every
 *  reordered row spans the full 12-column track, so reordering never leaves a
 *  hole. Only fixed section ids reach the CSS, never request input. */
export function lensStyles(lens: Lens): string {
  const grid = ".pf-main-grid";
  const at = (id: LensSectionId) => `${grid} > [data-section="${id}"]`;
  const restOrder = LEAD_ORDER_START + lens.lead.length;
  const rules = [
    `${grid} > [data-section] { order: ${restOrder}; }`,
    ...lens.lead.map((id, i) => `${at(id)} { order: ${LEAD_ORDER_START + i}; }`),
    ...lens.fold.map((id) => `${at(id)} { order: ${restOrder + 1}; }`),
    // The "Find similar profiles" footer closes the grid whatever the lens.
    `${at("explore")} { order: ${restOrder + 2}; }`,
  ];
  if (lens.highlight.length) {
    rules.push(`${lens.highlight.map(at).join(", ")} { border-radius: 22px; box-shadow: 0 0 0 6px rgba(109, 100, 246, 0.16); }`);
  }
  if (lens.fold.length) {
    const folded = lens.fold.map(at);
    rules.push(
      `${folded.join(", ")} { max-height: 180px; overflow: hidden; -webkit-mask-image: linear-gradient(#000 45%, transparent); mask-image: linear-gradient(#000 45%, transparent); }`,
      // A keyboard user tabbing into a clipped link must be able to see it.
      `${folded.map((s) => `${s}:focus-within`).join(", ")} { max-height: none; -webkit-mask-image: none; mask-image: none; }`,
    );
  }
  return rules.join("\n");
}
