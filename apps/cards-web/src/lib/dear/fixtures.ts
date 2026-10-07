import type { Activity, IntroRequest, Letter, SourceConnection } from "./types";

/**
 * Example data for the UI branch. Every person here is invented.
 * `TODAY` is fixed so server and client render the same relative dates.
 */
export const TODAY = "2026-10-08";

export const ME = "meera-iyer";

export const LETTERS: Letter[] = [
  {
    handle: "meera-iyer",
    name: "Meera Iyer",
    headline: "Founder, building tools that let AI agents work with people",
    location: "Bengaluru",
    claimed: true,
    signedAt: "2026-09-21",
    updatedAt: "2026-10-08",
    agentId: "zns:meera.9f4a",
    permissions: { speakForMe: true, findPeople: true, hireAgents: false },
    facts: [
      { id: "f1", kind: "building", text: "An identity card that AI agents can read and people can trust", source: "you", asOf: "2026-10-08", state: "ink", approvedAt: "2026-10-08", alsoIn: ["github"] },
      { id: "f2", kind: "looking_for", text: "A founding engineer who has shipped payments or identity", source: "you", asOf: "2026-10-02", state: "ink", approvedAt: "2026-10-02", expiresAt: "2026-11-01" },
      { id: "f3", kind: "can_help", text: "Agent protocols, MCP servers, and getting a first product out", source: "x", asOf: "2026-10-05", state: "ink", approvedAt: "2026-10-05", alsoIn: ["github"] },
      { id: "f4", kind: "shipped", text: "Intro requests between two people's agents", source: "claude", asOf: "2026-10-07", state: "ink", approvedAt: "2026-10-07" },
      { id: "f5", kind: "role", text: "Founder at Lantern Labs", source: "linkedin", asOf: "2024-03-01", state: "ink", approvedAt: "2026-09-21" },
      { id: "f6", kind: "location", text: "Based in Bengaluru", source: "linkedin", asOf: "2023-06-01", state: "ink", approvedAt: "2026-09-21" },
      { id: "f7", kind: "skill", text: "Python, TypeScript, Postgres", source: "github", asOf: "2026-10-06", state: "ink", approvedAt: "2026-09-21" },
      // struck: the agent must never say these
      { id: "f8", kind: "role", text: "Open to work", source: "linkedin", asOf: "2023-02-11", state: "struck" },
      { id: "f9", kind: "role", text: "Backend engineer at Northwind", source: "linkedin", asOf: "2021-08-01", state: "struck" },
      // pencil: waiting in the inbox
      { id: "p1", kind: "shipped", text: "A share page with a large QR code and a short link", source: "cursor", asOf: "2026-10-08", state: "pencil", triage: "looks_right", note: "You merged this today. It matches what you say you are building." },
      { id: "p2", kind: "can_help", text: "Reviewing early-stage pitch decks", source: "x", asOf: "2026-10-04", state: "pencil", triage: "looks_right", note: "Three posts this week offering this." },
      { id: "p3", kind: "building", text: "A Telegram bot for meeting approvals", source: "claude", asOf: "2026-10-03", state: "pencil", triage: "needs_look", note: "This may be an experiment rather than something you are building. Your call." },
      { id: "p4", kind: "role", text: "Advisor at Pinecrest", source: "linkedin", asOf: "2022-11-01", state: "pencil", triage: "needs_look", note: "LinkedIn last changed this in 2022. Still true?" },
      { id: "p5", kind: "tool", text: "Uses a tool called worktree-sync", source: "cursor", asOf: "2026-10-01", state: "pencil", triage: "noise", note: "Looks like a repository name, not something people would ask about." },
      { id: "p6", kind: "building", text: "Fixing a flaky test in the payments suite", source: "claude", asOf: "2026-09-30", state: "pencil", triage: "noise", note: "A one-off task. I would leave this out." },
    ],
    history: [
      { role: "Founder", org: "Lantern Labs", from: "2024" },
      { role: "Staff engineer", org: "Kestrel Pay", from: "2021", to: "2024" },
      { role: "Backend engineer", org: "Northwind", from: "2018", to: "2021" },
    ],
    links: [
      { label: "GitHub", href: "https://github.com" },
      { label: "LinkedIn", href: "https://www.linkedin.com" },
    ],
  },
  {
    handle: "arjun-rao",
    name: "Arjun Rao",
    headline: "Payments engineer. Ledger systems, reconciliation, UPI",
    location: "Hyderabad",
    claimed: true,
    signedAt: "2026-09-30",
    updatedAt: "2026-10-06",
    agentId: "zns:arjun.2c71",
    permissions: { speakForMe: true, findPeople: true, hireAgents: true },
    facts: [
      { id: "a1", kind: "building", text: "A double-entry ledger service in Rust", source: "github", asOf: "2026-10-06", state: "ink", approvedAt: "2026-10-06" },
      { id: "a2", kind: "looking_for", text: "A small founding team to join as first engineer", source: "you", asOf: "2026-09-30", state: "ink", approvedAt: "2026-09-30", expiresAt: "2026-10-30" },
      { id: "a3", kind: "can_help", text: "Payment reconciliation and identity verification flows", source: "you", asOf: "2026-09-30", state: "ink", approvedAt: "2026-09-30" },
      { id: "a4", kind: "role", text: "Senior engineer at Tallybook", source: "linkedin", asOf: "2025-01-01", state: "ink", approvedAt: "2026-09-30" },
    ],
    history: [{ role: "Senior engineer", org: "Tallybook", from: "2022" }],
    links: [{ label: "GitHub", href: "https://github.com" }],
  },
  {
    handle: "sana-qureshi",
    name: "Sana Qureshi",
    headline: "Design engineer for developer tools",
    location: "Lisbon",
    claimed: true,
    signedAt: "2026-10-01",
    updatedAt: "2026-09-12",
    agentId: "zns:sana.77be",
    permissions: { speakForMe: true, findPeople: false, hireAgents: false },
    facts: [
      { id: "s1", kind: "building", text: "A component library for terminal-style web apps", source: "github", asOf: "2026-09-12", state: "ink", approvedAt: "2026-09-12" },
      { id: "s2", kind: "can_help", text: "Onboarding flows and first-run experience for technical products", source: "you", asOf: "2026-10-01", state: "ink", approvedAt: "2026-10-01" },
      { id: "s3", kind: "looking_for", text: "Two design partners building AI tools", source: "you", asOf: "2026-08-20", state: "ink", approvedAt: "2026-08-20", expiresAt: "2026-09-19" },
    ],
    history: [{ role: "Design engineer", org: "Independent", from: "2023" }],
    links: [],
  },
  {
    handle: "tomas-vidal",
    name: "Tomás Vidal",
    headline: "Machine learning engineer",
    location: "Madrid",
    claimed: false,
    updatedAt: "2025-04-02",
    permissions: { speakForMe: false, findPeople: false, hireAgents: false },
    facts: [
      { id: "t1", kind: "role", text: "Machine learning engineer at Orbita", source: "linkedin", asOf: "2025-04-02", state: "pencil" },
      { id: "t2", kind: "skill", text: "PyTorch, retrieval systems", source: "github", asOf: "2025-03-10", state: "pencil" },
    ],
    history: [],
    links: [],
  },
];

export const INTROS: IntroRequest[] = [
  {
    id: "i1",
    from: { name: "Arjun Rao", handle: "arjun-rao", via: "agent", headline: "Payments engineer" },
    why: "Arjun is looking for a founding team, and has shipped ledgers and identity checks. Your letter says you are looking for exactly that.",
    asks: ["A 20-minute call this week"],
    at: "2026-10-08",
    status: "waiting",
    matched: "A founding engineer who has shipped payments or identity",
  },
  {
    id: "i2",
    from: { name: "Leah Brandt", via: "person", headline: "Partner at an early-stage fund" },
    why: "I read your posts on agent protocols and would like to hear what you are building.",
    asks: ["An email reply", "Your deck, if you have one"],
    at: "2026-10-06",
    status: "waiting",
    matched: "An identity card that AI agents can read and people can trust",
  },
  {
    id: "i3",
    from: { name: "Sana Qureshi", handle: "sana-qureshi", via: "agent", headline: "Design engineer" },
    why: "Sana is looking for design partners building AI tools and can help with onboarding.",
    asks: ["A 20-minute call"],
    at: "2026-09-29",
    status: "accepted",
  },
];

export const ACTIVITY: Activity = {
  weekOf: "2026-10-05",
  views: 148,
  agentAsks: 23,
  introsAccepted: 1,
  asks: [
    { id: "q1", at: "2026-10-08", who: "An agent on Claude", kind: "agent", question: "Who is building identity for AI agents in Bengaluru?", answered: true },
    { id: "q2", at: "2026-10-07", who: "Arjun Rao's agent", kind: "agent", question: "Founders hiring a first engineer with payments experience", answered: true },
    { id: "q3", at: "2026-10-07", who: "A visitor", kind: "person", question: "Does she take on advisory work?", answered: false },
    { id: "q4", at: "2026-10-06", who: "An agent on ChatGPT", kind: "agent", question: "People who can review an MCP server design", answered: true },
    { id: "q5", at: "2026-10-05", who: "A visitor", kind: "person", question: "What is her rate for consulting?", answered: false },
  ],
};

export const SOURCES: SourceConnection[] = [
  { id: "linkedin", label: "LinkedIn", group: "profile", connected: true, lastRead: "2026-09-21", inked: 2, pencilled: 1, goodFor: "Who you are and where you have been. Slow to change, often stale.", autoPublic: false },
  { id: "github", label: "GitHub", group: "work", connected: true, lastRead: "2026-10-08", inked: 2, pencilled: 0, goodFor: "What you actually ship.", autoPublic: false },
  { id: "x", label: "X", group: "work", connected: true, lastRead: "2026-10-05", inked: 1, pencilled: 1, goodFor: "What you talk about and offer to help with.", autoPublic: false },
  { id: "claude", label: "Claude", group: "assistant", connected: true, lastRead: "2026-10-07", inked: 1, pencilled: 2, goodFor: "What you are working on this week. Freshest, and the noisiest.", autoPublic: false },
  { id: "cursor", label: "Cursor", group: "assistant", connected: true, lastRead: "2026-10-08", inked: 0, pencilled: 2, goodFor: "What you are working on this week.", autoPublic: false },
  { id: "chatgpt", label: "ChatGPT", group: "assistant", connected: false, inked: 0, pencilled: 0, goodFor: "What you are working on this week.", autoPublic: false },
];
