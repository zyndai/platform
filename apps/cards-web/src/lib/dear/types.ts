/**
 * Dear Agent — front-end data contracts.
 *
 * These are the shapes the new UI renders. They are deliberately close to the
 * "one CardView" proposed in the engineering guide (slice S06): every public
 * fact carries its source, the date it was last true and its approval state,
 * so the page, the agent JSON and search can all be derived from one object.
 *
 * Nothing here talks to a backend yet; see `repo.ts`.
 */

/** pencil = found by the agent, private · ink = approved by the owner, public · struck = never say this */
export type InkState = "pencil" | "ink" | "struck";

export type SourceId =
  | "you"
  | "linkedin"
  | "github"
  | "x"
  | "claude"
  | "cursor"
  | "chatgpt";

export type FactKind =
  | "building"
  | "looking_for"
  | "can_help"
  | "role"
  | "shipped"
  | "skill"
  | "tool"
  | "location";

/** How the inbox groups a pencilled fact before the owner has looked at it. */
export type Triage = "looks_right" | "needs_look" | "noise";

export interface Fact {
  id: string;
  kind: FactKind;
  text: string;
  source: SourceId;
  /** ISO date the source says this was last true. */
  asOf: string;
  state: InkState;
  /** ISO date the owner inked it. Absent while in pencil. */
  approvedAt?: string;
  /** ISO date after which the line fades and asks to be renewed ("looking for" defaults to 30 days). */
  expiresAt?: string;
  /** Other sources that say the same thing. */
  alsoIn?: SourceId[];
  triage?: Triage;
  /** One line from the agent on why it pencilled this in, or why it doubts it. */
  note?: string;
}

export interface Permissions {
  speakForMe: boolean;
  findPeople: boolean;
  hireAgents: boolean;
}

export interface Letter {
  handle: string;
  name: string;
  headline: string;
  location: string;
  /** False = created from public data and not yet claimed by the person. */
  claimed: boolean;
  signedAt?: string;
  updatedAt: string;
  /** Network identity of this person's agent (zns:…). */
  agentId?: string;
  permissions: Permissions;
  facts: Fact[];
  history: { role: string; org: string; from: string; to?: string }[];
  links: { label: string; href: string }[];
}

export interface IntroRequest {
  id: string;
  from: { name: string; handle?: string; via: "person" | "agent"; headline?: string };
  why: string;
  asks: string[];
  at: string;
  status: "waiting" | "accepted" | "declined";
  /** The line in the owner's letter that the request matched. */
  matched?: string;
}

export interface AskEvent {
  id: string;
  at: string;
  who: string;
  kind: "agent" | "person";
  question: string;
  /** Whether the letter had an inked line that answered it. */
  answered: boolean;
}

export interface Activity {
  weekOf: string;
  views: number;
  agentAsks: number;
  introsAccepted: number;
  asks: AskEvent[];
}

export interface SourceConnection {
  id: SourceId;
  label: string;
  group: "profile" | "work" | "assistant";
  connected: boolean;
  lastRead?: string;
  inked: number;
  pencilled: number;
  /** What this source is good for, in the owner's words. */
  goodFor: string;
  /** Whether anything from this source may go public without a tap. Always false in this design. */
  autoPublic: false;
}

export interface SearchHit {
  letter: Letter;
  /** The inked lines that matched, shown as the reason. */
  reasons: Fact[];
}
