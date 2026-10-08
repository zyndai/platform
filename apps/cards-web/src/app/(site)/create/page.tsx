"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Geist, Geist_Mono, Space_Grotesk } from "next/font/google";

import { useAuth } from "@/hooks/useAuth";
import { createClient } from "@/lib/supabase/client";
import { CARDS_API } from "@/lib/cards";
import { setClaimHandle } from "@/lib/auth/next-cookie";
import { startLinkedInOAuth } from "@/lib/auth/session";
import type { AgentProfileCard, OnboardStatus, Project, ScrapeWarning, WritingSample } from "@/lib/cards";
import { MemoryProviderOnboard } from "@/components/memory/MemoryProviderOnboard";
import { AutoGrowTextArea } from "@/components/AutoGrowTextArea";
import { imgProxyUrl } from "@/lib/avatar";
import { claimHeaders, forgetClaimToken, saveClaimToken } from "@/lib/claim-tokens";
import { T, ZC_CSS, ZC_FONTS } from "./zc-theme";

const { SANS, DISPLAY, MONO } = ZC_FONTS;

// Geist / Geist Mono / Space Grotesk are the design's three faces. Loaded via
// next/font so they self-host and don't fight the site-wide Webflow CSS.
const geist = Geist({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--zc-sans" });
const geistMono = Geist_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--zc-mono" });
const spaceGrotesk = Space_Grotesk({ subsets: ["latin"], weight: ["500", "600", "700"], variable: "--zc-display" });
const FONT_VARS = `${geist.variable} ${geistMono.variable} ${spaceGrotesk.variable}`;

// Memory layer (api.zynd.ai) — same host the /connect and /findable pages use.
const ZYND_API = process.env.NEXT_PUBLIC_ZYND_API_URL || "https://api.zynd.ai";

// "exists": publish found a card this person (or these GitHub/X handles) already has.
type Phase   = "form" | "working" | "review" | "error" | "exists";
type UrlKind = "github" | "x" | "linkedin" | "website";

// ─── source palette (small colour square per source, per the design) ─────────
const CHIP: Record<UrlKind, { label: string; swatch: string }> = {
  github:   { label: "GitHub",   swatch: "#0B0B0B" },
  linkedin: { label: "LinkedIn", swatch: "#0A66C2" },
  x:        { label: "X",        swatch: "#1C1C1C" },
  website:  { label: "Website",  swatch: "#7B72E9" },
};

const QUICK_ADD: { kind: UrlKind; domain: string }[] = [
  { kind: "github",   domain: "github.com/" },
  { kind: "linkedin", domain: "linkedin.com/in/" },
  { kind: "x",        domain: "x.com/" },
];

// ─── one-at-a-time questions shown during extraction ─────────────────────────
type QuestionType = "chips" | "text";
const QUESTIONS: { id: string; label: string; type: QuestionType; options?: string[] }[] = [
  {
    id: "working_on", type: "chips",
    label: "What are you working on?",
    options: [
      "Building a startup", "Building with AI", "Open source", "Side project", "Indie hacking",
      "B2B SaaS", "Consumer apps", "Deep tech / research", "Freelancing", "At a company",
      "Doing research", "Grad school", "Writing", "Teaching / mentoring", "Community building",
      "Design / creative work", "Investing", "Job hunting",
    ],
  },
  {
    id: "can_help", type: "chips",
    label: "What can you help people with?",
    options: [
      "Code review", "System design", "ML / AI", "Cloud / infra", "Data / analytics", "Security",
      "Technical interviews", "Hiring", "Career advice", "Fundraising", "Pitching / storytelling",
      "Sales", "Marketing", "Go-to-market", "Design", "Legal / compliance", "Immigration / visas",
      "Public speaking",
    ],
  },
  {
    id: "connect_with", type: "chips",
    label: "Who would you like to connect with?",
    options: [
      "Founders", "Investors", "Engineers", "ML Researchers", "Product Managers", "Designers",
      "Operators", "Scientists", "Recruiters", "Mentors", "Potential co-founders", "Customers",
      "Students", "Writers", "DevRel", "Researchers in my field", "Healthcare builders",
      "Robotics people",
    ],
  },
  {
    id: "love_talking", type: "chips",
    label: "What do you love talking about?",
    options: [
      "AI / ML", "Agentic AI", "Startups", "Developer tools", "Open source", "Web3 / Crypto",
      "Climate tech", "Robotics", "Hardware", "Design", "Research", "SaaS",
      "Engineering culture", "Books", "Philosophy", "Personal finance", "Gaming",
      "History / science",
    ],
  },
  {
    id: "location", type: "text",
    label: "Where are you based?",
  },
  {
    id: "booking", type: "text",
    label: "Got a booking link?",
  },
];

function commitCustomValues(
  existing: Set<string>,
  options: string[] | undefined,
  raw: string,
): Set<string> {
  const have = new Set([...existing].map(s => s.toLowerCase()));
  const next = new Set(existing);
  for (const part of raw.split(",")) {
    const v = part.trim();
    if (!v) continue;
    const key = v.toLowerCase();
    if (have.has(key)) continue;
    const preset = (options ?? []).find(o => o.toLowerCase() === key);
    next.add(preset ?? v);
    have.add(key);
  }
  return next;
}

function mergeChipDrafts(
  selections: Record<string, Set<string>>,
  customs: Record<string, string>,
): Record<string, Set<string>> {
  const out: Record<string, Set<string>> = { ...selections };
  for (const q of QUESTIONS) {
    if (q.type !== "chips") continue;
    const raw = customs[q.id]?.trim();
    if (!raw) continue;
    out[q.id] = commitCustomValues(out[q.id] ?? new Set(), q.options, raw);
  }
  return out;
}

function prevQuestionIndex(current: number): number {
  return Math.max(0, current - 1);
}

// ─── helpers ──────────────────────────────────────────────────────────────────
function detectKind(url: string): UrlKind {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host === "github.com" || host.endsWith(".github.com")) return "github";
    if (host === "x.com" || host === "twitter.com" || host.endsWith(".twitter.com")) return "x";
    if (host === "linkedin.com" || host.endsWith(".linkedin.com")) return "linkedin";
  } catch { /* invalid — treat as website */ }
  return "website";
}

function shortenUrl(url: string): string {
  try {
    const u = new URL(url);
    return (u.hostname + u.pathname).replace(/\/$/, "").slice(0, 38);
  } catch {
    return url.slice(0, 38);
  }
}

function KindSquare({ kind, size = 13 }: { kind: UrlKind; size?: number }) {
  const bg = CHIP[kind].swatch;
  const r = Math.max(3, Math.round(size * 0.3));
  const p = size * 0.15;
  const inner = size - p * 2;
  return (
    <span style={{ width: size, height: size, borderRadius: r, background: bg, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
      <svg width={inner} height={inner} viewBox="0 0 16 16" fill="none" aria-hidden>
        {kind === "github" && (
          <path fill="#fff" fillRule="evenodd" d="M8 .5C3.858.5.5 3.882.5 8.056a7.56 7.56 0 0 0 5.129 7.17c.374.077.51-.163.51-.363 0-.175-.012-.775-.012-1.4-2.085.45-2.52-.9-2.52-.9-.337-.875-.832-1.1-.832-1.1-.682-.463.05-.463.05-.463.757.05 1.156.775 1.156.775.67 1.15 1.75.825 2.184.625.062-.487.261-.825.473-1.012-1.664-.175-3.415-.825-3.415-3.725 0-.825.299-1.5.77-2.025-.075-.187-.336-.963.074-2 0 0 .633-.2 2.06.775A7.2 7.2 0 0 1 8 5.156c.633 0 1.28.087 1.875.25 1.428-.975 2.061-.775 2.061-.775.41 1.038.15 1.813.074 2 .473.525.77 1.2.77 2.025 0 2.9-1.752 3.538-3.428 3.725.274.238.509.688.509 1.4 0 1.013-.012 1.825-.012 2.075 0 .2.136.438.509.363A7.56 7.56 0 0 0 15.5 8.056C15.5 3.882 12.142.5 8 .5" clipRule="evenodd" />
        )}
        {kind === "linkedin" && (
          <>
            <rect x="1" y="1" width="14" height="14" rx="2.5" fill="#0A66C2" />
            <path fill="#fff" d="M4.2 6.4h1.8V12H4.2V6.4zm.9-2.8a1.05 1.05 0 1 1 0 2.1 1.05 1.05 0 0 1 0-2.1zM7.4 6.4h1.73v.76h.02c.24-.46.83-.95 1.71-.95 1.83 0 2.17 1.2 2.17 2.77V12h-1.8V9.32c0-.67-.01-1.53-.93-1.53-.94 0-1.08.73-1.08 1.48V12H7.4V6.4z" />
          </>
        )}
        {kind === "x" && (
          <path fill="#fff" fillRule="evenodd" d="M1.5 1.5h3.9l2.28 3.24 2.67-3.24H12l-3.6 4.38L13 14.5H9.1L6.63 11l-3 3.5H2l3.87-4.5zm2.1 1.2 6.6 9.6h1.2L4.8 2.7z" clipRule="evenodd" />
        )}
        {kind === "website" && (
          <circle cx="8" cy="8" r="6" stroke="#fff" strokeWidth="1.5" fill="none" />
        )}
      </svg>
    </span>
  );
}

// ─── field ────────────────────────────────────────────────────────────────────
function TextField({ label, value, onChange, rows, placeholder, autoGrow }: {
  label: string; value: string; onChange: (v: string) => void;
  rows?: number; placeholder?: string; autoGrow?: boolean;
}) {
  const style: React.CSSProperties = {
    width: "100%", padding: "13px 15px", fontSize: "15px", lineHeight: 1.5,
    border: `1px solid ${T.border}`, borderRadius: "14px",
    background: T.surface, color: T.ink, outline: "none",
    fontFamily: SANS, boxSizing: "border-box",
    transition: "border-color .14s",
  };
  return (
    <div>
      <div style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".14em", textTransform: "uppercase", color: T.muted, marginBottom: "9px" }}>
        {label}
      </div>
      {rows ? (
        autoGrow ? (
          <AutoGrowTextArea
            value={value}
            onChange={onChange}
            placeholder={placeholder}
            minRows={rows}
            className="zc-field"
            style={{ ...style, resize: "none", overflowY: "hidden" }}
          />
        ) : (
          <textarea rows={rows} value={value} placeholder={placeholder} className="zc-field"
            onChange={e => onChange(e.target.value)}
            style={{ ...style, resize: "none" }} />
        )
      ) : (
        <input type="text" value={value} placeholder={placeholder} className="zc-field"
          onChange={e => onChange(e.target.value)}
          style={style} />
      )}
    </div>
  );
}

// ─── apply user answers to card ───────────────────────────────────────────────
function applyAnswers(
  card: AgentProfileCard,
  selections: Record<string, Set<string>>,
  locationInput: string,
): AgentProfileCard {
  const c = { ...card, identity: { ...card.identity }, skills: [...card.skills], searchable_facts: [...card.searchable_facts] };

  const joinAnswers = (id: string) => [...(selections[id] ?? new Set<string>())];

  const name = c.identity.name || "This person";

  const workingOn = joinAnswers("working_on");
  if (workingOn.length > 0) {
    c.searchable_facts = [...c.searchable_facts, `${name} — working on ${workingOn.join(", ")} — Zynd`];
    if (!c.summary) c.summary = `Currently working on: ${workingOn.join(", ")}.`;
  }

  const canHelp = joinAnswers("can_help");
  if (canHelp.length > 0) {
    const newSkills = canHelp
      .map(n => ({ name: n, level: "intermediate" as const, evidence_count: 1 }))
      .filter(ns => !c.skills.find(s => s.name.toLowerCase() === ns.name.toLowerCase()));
    c.skills = [...c.skills, ...newSkills];
  }

  const connectWith = joinAnswers("connect_with");
  if (connectWith.length > 0) {
    c.searchable_facts = [...c.searchable_facts, `${name} — looking to connect with ${connectWith.join(", ")} — Zynd`];
  }

  const loveTalking = joinAnswers("love_talking");
  if (loveTalking.length > 0) {
    c.searchable_facts = [...c.searchable_facts, `${name} — loves talking about ${loveTalking.join(", ")} — Zynd`];
  }

  // The location the user typed is authoritative: extraction may have
  // guessed one from the resume/LinkedIn while the questions were being
  // answered (the job is still scraping then) — an explicit answer always
  // wins over the guess.
  if (locationInput.trim()) {
    c.identity.location = locationInput.trim();
  }

  return c;
}

// ─── S08 endowed progress: the ring starts at 40% (what was scraped), never
// resets, and lands at 100 on publish — people finish what looks started. ────
function ProgressRing({ percent }: { percent: number }) {
  const R = 15;
  const C = 2 * Math.PI * R;
  const offset = C * (1 - Math.min(100, Math.max(0, percent)) / 100);
  return (
    <svg width="46" height="46" viewBox="0 0 36 36" aria-label={`${percent}% complete`} role="img" style={{ flexShrink: 0 }}>
      <circle cx="18" cy="18" r={R} fill="none" stroke="rgba(255,255,255,.28)" strokeWidth="3" />
      <circle cx="18" cy="18" r={R} fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round"
        strokeDasharray={C} strokeDashoffset={offset} transform="rotate(-90 18 18)" style={{ transition: "stroke-dashoffset .5s ease" }} />
      <text x="18" y="21" textAnchor="middle" fontSize="9.5" fontWeight="700" fill="#fff" fontFamily={MONO}>{percent}%</text>
    </svg>
  );
}

function progressPercent(phase: Phase, jobDone: boolean, published: string | null): number {
  if (published) return 100;
  if (phase === "review") return jobDone ? 85 : 75;
  if (phase === "working") return jobDone ? 70 : 55;
  return 40;
}

// ─── avatar with a fallback for dead / hotlink-blocked scraped URLs ──────────
function Avatar({ url, name }: { url: string; name: string }) {
  const [broken, setBroken] = useState(false);
  // Third-party CDN avatars (LinkedIn/X/GitHub) get blocked in some
  // browsers — serve through the first-party /api/img proxy.
  const src = url && !broken ? imgProxyUrl(url) : null;
  if (!src) {
    return (
      <span className="zc-avatar" style={{ background: T.accent, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", font: `600 22px/1 ${DISPLAY}` }}>
        {(name || "?").trim().charAt(0).toUpperCase()}
      </span>
    );
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt="" className="zc-avatar" onError={() => setBroken(true)} />;
}

// ─── skills editor for the review screen ─────────────────────────────────────
const SKILL_LEVEL_LABEL: Record<string, string> = {
  expert: "Expert", advanced: "Advanced", intermediate: "Intermediate", beginner: "Beginner",
};

function SkillsEditor({ skills, onSkillsChange }: {
  skills: AgentProfileCard["skills"];
  onSkillsChange: (skills: AgentProfileCard["skills"]) => void;
}) {
  const [input, setInput] = useState("");

  const add = (raw: string) => {
    const parts = raw.split(",").map(p => p.trim()).filter(Boolean);
    if (parts.length === 0) return;
    const next = [...skills];
    for (const name of parts) {
      if (next.some(s => s.name.toLowerCase() === name.toLowerCase())) continue;
      next.push({ name, level: "intermediate" as const, evidence_count: 0 });
    }
    if (next.length !== skills.length) onSkillsChange(next);
    setInput("");
  };

  const remove = (name: string) => onSkillsChange(skills.filter(s => s.name !== name));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
      {skills.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
          {skills.map(s => (
            <span key={s.name} className="zc-chip-enter"
              style={{ display: "inline-flex", alignItems: "center", gap: "8px", background: T.surface, border: `1px solid ${T.border}`, borderRadius: "999px", padding: "7px 8px 7px 13px" }}>
              <span style={{ font: `500 13px/1 ${SANS}`, color: T.ink }}>{s.name}</span>
              <span style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".06em", textTransform: "uppercase", color: T.accentHi, background: T.ctaOffBg, borderRadius: "999px", padding: "3px 7px" }}>
                {SKILL_LEVEL_LABEL[s.level] ?? "Intermediate"}
              </span>
              <button type="button" className="zc-x" aria-label={`Remove ${s.name}`}
                onClick={() => remove(s.name)}
                style={{ font: `400 14px/1 ${SANS}`, color: T.muted, background: "none", border: "none", padding: "0 3px", cursor: "pointer" }}>
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <input
        type="text"
        value={input}
        onChange={e => setInput(e.target.value)}
        onKeyDown={e => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            add(input);
          }
        }}
        onBlur={() => { if (input.trim()) add(input); }}
        placeholder={skills.length === 0 ? "Add a skill — Enter or comma to add" : "Add another — Enter or comma"}
        className="zc-field"
        style={{
          width: "100%", padding: "13px 15px", fontSize: "15px", lineHeight: 1.5,
          border: `1px solid ${T.border}`, borderRadius: "14px",
          background: T.surface, color: T.ink, outline: "none",
          fontFamily: SANS, boxSizing: "border-box",
          transition: "border-color .14s",
        }}
      />
    </div>
  );
}

// ─── review section header (label · total, plus a hint once rows are removed) ─
function SectionLabel({ label, total, kept }: { label: string; total?: number; kept?: number }) {
  const removed = total !== undefined && kept !== undefined && kept < total;
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px" }}>
      <span style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".14em", textTransform: "uppercase", color: T.muted }}>
        {label}{total !== undefined ? ` · ${total}` : ""}
      </span>
      {removed && (
        <span style={{ font: `400 12px/1 ${SANS}`, color: T.accentHi }}>{kept} will publish</span>
      )}
    </div>
  );
}

// ─── review-screen exclusions ─────────────────────────────────────────────────
const projectKey = (p: Project, i: number) => `project:${p.url || i}`;
const sampleKey  = (i: number) => `sample:${i}`;

/** The card as it will be published: scraped rows the user removed are dropped. */
function publishableCard(card: AgentProfileCard, excluded: Set<string>): AgentProfileCard {
  if (excluded.size === 0) return card;
  return {
    ...card,
    projects: card.projects.filter((p, i) => !excluded.has(projectKey(p, i))),
    writing_samples: card.writing_samples.filter((_, i) => !excluded.has(sampleKey(i))),
  };
}

async function getToken(): Promise<string | null> {
  const { data } = await createClient().auth.getSession();
  return data.session?.access_token ?? null;
}

// ─── page ─────────────────────────────────────────────────────────────────────
function CreateProfilePageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const editHandle = searchParams.get("edit");
  const notice = searchParams.get("notice");
  const { ready, authenticated, user } = useAuth();

  // Carry the post-OAuth destination in a cookie, not a query string. Some
  // Supabase allowlists match redirect URLs exactly, and a `?next=` query
  // breaks that match — GoTrue then falls back to its Site URL (localhost).
  const loginWithLinkedin = () => {
    if (published) setClaimHandle(published);
    void startLinkedInOAuth(published ? `/p/${encodeURIComponent(published)}` : "/create", "card");
  };

  const [phase, setPhase] = useState<Phase>("form");
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [card, setCard] = useState<AgentProfileCard | null>(null);

  // Review-screen exclusions. Kept out of `card` so removing a scraped project
  // or post is restorable — the filter is applied once, when publishing.
  const [excluded, setExcluded] = useState<Set<string>>(new Set());

  // URL chip input
  const [urls, setUrls] = useState<string[]>([]);
  const [inputVal, setInputVal] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);
  const [resume, setResume] = useState<File | null>(null);
  const [inputFocused, setInputFocused] = useState(false);

  // One-at-a-time questions
  const [questionIndex, setQuestionIndex] = useState(0);
  const [selections, setSelections] = useState<Record<string, Set<string>>>({
    working_on: new Set(), can_help: new Set(), connect_with: new Set(), love_talking: new Set(),
  });
  const [customs, setCustoms] = useState<Record<string, string>>({
    working_on: "", can_help: "", connect_with: "", love_talking: "",
  });
  const [locationInput, setLocationInput] = useState("");
  const [calendlyInput, setCalendlyInput] = useState("");
  const [googleCalInput, setGoogleCalInput] = useState("");

  const [jobDone, setJobDone] = useState(false);
  const [existingHandle, setExistingHandle] = useState<string | null>(null);
  const [existingPublished, setExistingPublished] = useState(true);
  // Set once publishing succeeds — flips the review column into the
  // post-publish "claim your card" screen.
  const [published, setPublished] = useState<string | null>(null);
  const [existsHandle, setExistsHandle] = useState<string | null>(null);
  // S08: the memory-key step is off the default path (moved to the owner
  // home / edit page). Nothing here blocks the first win.
  const [memoryStep, setMemoryStep] = useState<"ask" | "done">("done");
  const [copied, setCopied] = useState(false);
  const [urlWarnings, setUrlWarnings] = useState<ScrapeWarning[]>([]);
  const [fixingUrl, setFixingUrl] = useState<string | null>(null);
  const [fixUrlInput, setFixUrlInput] = useState("");

  // Custom URL handle (review screen)
  const [customHandle, setCustomHandle] = useState("");
  const [handleAvailable, setHandleAvailable] = useState<boolean | null>(null);
  const [handleChecking, setHandleChecking] = useState(false);
  const handleCheckRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Add more sources (review screen re-extract)
  const [addMoreUrls, setAddMoreUrls] = useState<string[]>([]);
  const [addMoreInput, setAddMoreInput] = useState("");
  const [addMoreResume, setAddMoreResume] = useState<File | null>(null);
  const addMoreFileRef = useRef<HTMLInputElement>(null);
  const addMoreInputRef = useRef<HTMLInputElement>(null);

  // S08 claim-first: published unclaimed cards matching a pasted LinkedIn URL.
  const [claimCandidates, setClaimCandidates] = useState<{ handle: string; name: string; headline: string }[]>([]);
  // S08 auth-before-build: offer sign-in before the scrape starts.
  const [authNudge, setAuthNudge] = useState(false);
  const authNudgeRef = useRef(false);

  // Photo change
  const [showPhotoInput, setShowPhotoInput] = useState(false);
  const [photoUrlInput, setPhotoUrlInput] = useState("");
  const [photoUploading, setPhotoUploading] = useState(false);
  const photoFileRef = useRef<HTMLInputElement>(null);
  const pendingCardRef = useRef<AgentProfileCard | null>(null);
  const questionIndexRef = useRef(0);
  const jobDoneRef = useRef(false);
  const selectionsRef = useRef(selections);
  const customsRef = useRef(customs);
  const locationRef = useRef(locationInput);
  const calendlyRef = useRef(calendlyInput);

  // Keep refs in sync
  useEffect(() => { selectionsRef.current = selections; }, [selections]);
  useEffect(() => { customsRef.current = customs; }, [customs]);
  useEffect(() => { locationRef.current = locationInput; }, [locationInput]);
  useEffect(() => { calendlyRef.current = calendlyInput; }, [calendlyInput]);

  const fileRef    = useRef<HTMLInputElement>(null);
  const inputRef   = useRef<HTMLInputElement>(null);
  const pollRef    = useRef<ReturnType<typeof setInterval> | null>(null);
  const customRefs = useRef<Record<string, HTMLInputElement | null>>({});

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  // Check if this authenticated user already has a card
  useEffect(() => {
    if (!authenticated || editHandle) return;
    getToken().then(token => {
      if (!token) return;
      fetch(`${CARDS_API}/cards/mine`, { headers: { Authorization: `Bearer ${token}` } })
        .then(r => (r.ok ? r.json() : null))
        .then(data => {
          if (data?.handle) {
            setExistingHandle(data.handle);
            setExistingPublished(data.card?.status === "published");
          }
        })
        .catch(() => { /* non-fatal — user just sees create form */ });
    });
  }, [authenticated, editHandle]);

  // Edit mode: load the existing card and jump to review
  useEffect(() => {
    if (!authenticated || !editHandle) return;
    fetch(`${CARDS_API}/cards/by-handle/${encodeURIComponent(editHandle)}`)
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then((data: AgentProfileCard) => {
        setCard(data);
        setPhase("review");
      })
      .catch(() => {
        setError("Couldn't load that card for editing.");
        setPhase("error");
      });
  }, [authenticated, editHandle]);

  // Seeded from the landing page paste bar: `?url=<link>` lands here as the
  // first source chip so the visitor never retypes what they already pasted.
  const seededUrl = searchParams.get("url");
  const seededRef = useRef(false);
  useEffect(() => {
    if (seededRef.current || !seededUrl) return;
    seededRef.current = true;
    seededUrl.split(/\s+/).filter(Boolean).forEach(addUrl);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seededUrl]);

  // Pre-fill the custom handle field when the user arrives from the landing page
  // with ?handle=<slug> — they typed it there so honour it exactly.
  const seededHandle = searchParams.get("handle");
  const seededHandleRef = useRef(false);
  useEffect(() => {
    if (seededHandleRef.current || !seededHandle) return;
    seededHandleRef.current = true;
    const slug = seededHandle.toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 30);
    if (slug.length >= 2) setCustomHandle(slug);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seededHandle]);

  // S08 claim-first: as soon as a LinkedIn URL lands in the box, check for a
  // published, unclaimed card that matches it — claiming beats building a
  // duplicate.
  const linkedinUrls = urls.filter((u) => detectKind(u) === "linkedin");
  useEffect(() => {
    if (phase !== "form" || linkedinUrls.length === 0) return;
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const res = await fetch(`${CARDS_API}/onboard/claim-candidates?linkedin=${encodeURIComponent(linkedinUrls[0])}`);
        if (!res.ok || cancelled) return;
        const data = await res.json();
        if (!cancelled) setClaimCandidates(Array.isArray(data.candidates) ? data.candidates : []);
      } catch { /* non-fatal */ }
    }, 500);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkedinUrls.join(","), phase]);

  // ── URL chip helpers ──
  function addUrl(raw: string) {
    const trimmed = raw.trim();
    if (!trimmed) return;
    const withProto = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
    try {
      const u = new URL(withProto);
      const host = u.hostname.toLowerCase();
      const needsHandle =
        host === "github.com" || host === "x.com" || host === "twitter.com" ||
        host === "linkedin.com";
      const pathPart = u.pathname.replace(/^\//, "").split("/")[0];
      if (needsHandle && !pathPart) {
        setUrlError(`Include your username — e.g. ${host}/yourusername`);
        return;
      }
    } catch { /* invalid URL — allow through so user sees it */ }
    setUrlError(null);
    if (!urls.includes(withProto)) setUrls(p => [...p, withProto]);
    setInputVal("");
  }

  function removeUrl(url: string) { setUrls(p => p.filter(u => u !== url)); }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); addUrl(inputVal); }
    else if (e.key === "Backspace" && !inputVal && urls.length > 0) setUrls(p => p.slice(0, -1));
  }

  function handlePaste(e: React.ClipboardEvent<HTMLInputElement>) {
    const pasted = e.clipboardData.getData("text").trim();
    if (!pasted) return;
    e.preventDefault();
    pasted.split(/\s+/).forEach(addUrl);
  }

  // ── Option picker helpers ──
  function toggleOption(id: string, opt: string) {
    setSelections(prev => {
      const next = new Set(prev[id]);
      if (next.has(opt)) next.delete(opt);
      else next.add(opt);
      const out = { ...prev, [id]: next };
      selectionsRef.current = out;
      return out;
    });
  }

  function commitDraft(id: string, options?: string[]) {
    const raw = (customRefs.current[id]?.value ?? customsRef.current[id] ?? "").trim();
    if (!raw) return;
    const nextSel = {
      ...selectionsRef.current,
      [id]: commitCustomValues(selectionsRef.current[id] ?? new Set(), options, raw),
    };
    selectionsRef.current = nextSel;
    setSelections(nextSel);
    const nextCustoms = { ...customsRef.current, [id]: "" };
    customsRef.current = nextCustoms;
    setCustoms(nextCustoms);
  }

  function onNext() {
    const q = QUESTIONS[questionIndexRef.current];
    if (q?.type === "chips") commitDraft(q.id, q.options);
    advanceQuestion();
  }

  function retreatQuestion() {
    const prev = prevQuestionIndex(questionIndexRef.current);
    questionIndexRef.current = prev;
    setQuestionIndex(prev);
  }

  // ── Submit ──
  const hasSource = urls.length > 0 || resume !== null;

  async function startOnboard(e: React.FormEvent) {
    e.preventDefault();
    // S08 auth-before-build: offer sign-in first so there is no post-publish
    // login wall — anonymous creation stays available as an explicit choice.
    if (!authenticated && !authNudgeRef.current) {
      setAuthNudge(true);
      authNudgeRef.current = true;
      return;
    }
    setError(null);
    setAuthNudge(false);
    setPhase("working");
    const form = new FormData();
    urls.forEach(u => form.append("url", u));
    if (resume) form.append("resume", resume);
    try {
      const res = await fetch(`${CARDS_API}/onboard/start`, { method: "POST", body: form });
      if (!res.ok) throw new Error((await res.text()) || `Status ${res.status}`);
      const data = await res.json();
      setJobId(data.job_id);
      pollRef.current = setInterval(() => pollJob(data.job_id), 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start");
      setPhase("error");
    }
  }

  function goToReview(rawCard: AgentProfileCard) {
    const merged = mergeChipDrafts(selectionsRef.current, customsRef.current);
    selectionsRef.current = merged;
    setSelections(merged);
    setCustoms(p => {
      const cleared = { ...p };
      for (const q of QUESTIONS) if (q.type === "chips") cleared[q.id] = "";
      customsRef.current = cleared;
      return cleared;
    });
    const enriched = applyAnswers(rawCard, merged, locationRef.current);
    setCard(enriched);
    setPhase("review");
  }

  async function pollJob(id: string) {
    try {
      const res = await fetch(`${CARDS_API}/onboard/${id}`);
      if (!res.ok) return;
      const status: OnboardStatus = await res.json();
      if (status.status === "ready" && status.card) {
        clearInterval(pollRef.current!);
        pendingCardRef.current = status.card;
        jobDoneRef.current = true;
        setJobDone(true);
        if (status.url_warnings?.length) setUrlWarnings(status.url_warnings);
        // The location question is always asked now — prefill the field with
        // the extraction's best guess so the user can accept or correct it
        // (their answer is authoritative, see applyAnswers / publish).
        if (!locationRef.current.trim() && status.card?.identity.location) {
          setLocationInput(status.card.identity.location);
        }
        // If user already answered all questions, go to review immediately
        if (questionIndexRef.current >= QUESTIONS.length) {
          goToReview(status.card);
        }
        // else: user still on questions — they'll trigger goToReview via Next/Done button
      } else if (status.status === "error") {
        clearInterval(pollRef.current!);
        setError(status.error || "Unknown error");
        setPhase("error");
      }
    } catch { /* transient */ }
  }

  function advanceQuestion() {
    const next = questionIndexRef.current + 1;
    questionIndexRef.current = next;
    setQuestionIndex(next);
    if (next >= QUESTIONS.length && jobDoneRef.current && pendingCardRef.current) {
      goToReview(pendingCardRef.current);
    }
  }

  async function publish() {
    if (!card) return;
    setError(null);
    const token = await getToken();
    const authHeaders: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

    try {
      // Edit mode: PATCH the existing card directly (no job needed)
      if (editHandle) {
        const res = await fetch(`${CARDS_API}/cards/by-handle/${encodeURIComponent(editHandle)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json", ...authHeaders },
          body: JSON.stringify(publishableCard(card, excluded)),
        });
        if (res.status === 403) throw new Error("You don't own this card.");
        if (!res.ok) throw new Error((await res.text()) || `Status ${res.status}`);
        // Re-sync the memory layer so edited answers (working on, can help
        // with…) flow onto the profile's "currently" section right away.
        getToken().then(t => { if (t) syncMemoryOnClaim(t, editHandle); });
        router.push(`/p/${editHandle}`);
        return;
      }

      if (!jobId) return;
      const userAnswers: Record<string, string> = {};
      const chipAnswers = mergeChipDrafts(selections, customs);
      for (const q of QUESTIONS) {
        if (q.type === "chips") {
          const parts = [...(chipAnswers[q.id] ?? new Set<string>())];
          if (parts.length > 0) userAnswers[q.id] = parts.join(", ");
        } else if (q.id === "location" && locationInput.trim()) {
          userAnswers["location"] = locationInput.trim();
        } else if (q.id === "booking") {
          if (calendlyInput.trim()) userAnswers["calendly_url"] = calendlyInput.trim();
          if (googleCalInput.trim()) userAnswers["google_calendar_url"] = googleCalInput.trim();
        }
      }
      const res = await fetch(`${CARDS_API}/onboard/${jobId}/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders },
        body: JSON.stringify({
          card: publishableCard(card, excluded),
          user_answers: userAnswers,
          owner_email: user?.email ?? null,
          custom_handle: customHandle.length >= 2 ? customHandle : undefined,
        }),
      });
      if (!res.ok) throw new Error((await res.text()) || `Status ${res.status}`);
      const publishedCard = await res.json();
      // One card per person: the API returns {existing, handle} instead of
      // creating a second card for the same owner or the same GitHub/X handles.
      if (publishedCard.existing) {
        setExistsHandle(publishedCard.handle);
        setPhase("exists");
        return;
      }
      const publishedHandle = publishedCard.handle || publishedCard.id;
      // Anonymous publish: the API returns a one-time claim token, required to
      // take ownership after signing in (sent as X-Claim-Token).
      if (typeof publishedCard.claim_token === "string") {
        saveClaimToken(publishedHandle, publishedCard.claim_token);
      }
      // Persist handle in localStorage so the creator can edit/claim without
      // signing in first — even after navigating to /p/[handle] directly.
      try {
        const stored: string[] = JSON.parse(localStorage.getItem("zynd_my_handles") || "[]");
        if (!stored.includes(publishedHandle)) stored.push(publishedHandle);
        localStorage.setItem("zynd_my_handles", JSON.stringify(stored));
      } catch { /* non-fatal */ }
      setClaimHandle(publishedHandle);
      // S08 first win: signed-in creators go straight to the "ask your own
      // card" welcome screen — no post-publish login wall, no detour.
      if (authenticated) {
        if (token) void syncMemoryOnClaim(token, publishedHandle);
        router.push(`/p/${encodeURIComponent(publishedHandle)}/welcome`);
        return;
      }
      // Anonymous publish: stay on the page and show the "you're live" claim
      // screen. Sign-in is offered there, not required before.
      setPublished(publishedHandle);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to publish");
      setPhase("error");
    }
  }

  // Claim the freshly published card when a signed-in user created it —
  // and when they sign in from the claim screen (an anonymous publish is
  // claimed by the first authenticated PATCH that carries its claim token).
  // Claiming also seeds the memory layer: exchange → declare key points from
  // the card → snapshot onto the card. The snapshot refresh is owner-only, so
  // it waits for the claim to land.
  useEffect(() => {
    if (!authenticated || !published || !card) return;
    getToken().then(async token => {
      if (!token) return;
      try {
        const res = await fetch(`${CARDS_API}/cards/by-handle/${encodeURIComponent(published)}`, {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
            ...claimHeaders(published),
          },
          body: JSON.stringify(publishableCard(card, excluded)),
        });
        if (res.ok) forgetClaimToken(published);
      } catch { /* non-fatal — card is live either way */ }
      syncMemoryOnClaim(token, published);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authenticated, published]);

  // Seed the memory layer from the claimed card, then pull the snapshot onto
  // the card so the public profile shows what the person is currently up to.
  // working_on → "Currently building", can_help_with → "Expert in",
  // love_talking_about → "Learning", skills as expertise fallback.
  async function syncMemoryOnClaim(supabaseToken: string, handle: string) {
    try {
      const ex = await fetch(`${ZYND_API}/token/exchange`, {
        method: "POST",
        headers: { Authorization: `Bearer ${supabaseToken}` },
      });
      if (!ex.ok) return;
      const { token: zyndToken } = await ex.json();
      if (!zyndToken) return;
      const declarations: { predicate: string; value: string }[] = [];
      const push = (predicate: string, values: string[] | undefined, cap = 5) => {
        for (const v of (values ?? []).slice(0, cap)) {
          const t = v.trim();
          if (t && t.length <= 120) declarations.push({ predicate, value: t });
        }
      };
      push("is_building", card?.working_on);
      push("has_expertise_in", card?.can_help_with);
      push("is_learning", card?.love_talking_about);
      if (!(card?.can_help_with ?? []).length) push("has_expertise_in", card?.skills.map((s) => s.name));
      const location = card?.identity?.location?.trim();
      if (location) declarations.push({ predicate: "is_located_in", value: location });
      if (declarations.length) {
        await fetch(`${ZYND_API}/me/findability/declare-batch`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${zyndToken}` },
          body: JSON.stringify({ declarations: declarations.slice(0, 50) }),
        }).catch(() => { /* non-fatal */ });
      }
    } catch { /* non-fatal — memory is best-effort on claim */ }
    await fetch(`${CARDS_API}/cards/by-handle/${encodeURIComponent(handle)}/refresh-memory`, {
      method: "POST",
      headers: { Authorization: `Bearer ${supabaseToken}` },
    }).catch(() => { /* non-fatal */ });
  }

  function toggleExcluded(key: string) {
    setExcluded(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

  function updateCard(patch: Partial<AgentProfileCard>) {
    setCard(prev => prev ? { ...prev, ...patch } : prev);
  }

  function onCustomHandleChange(val: string) {
    const slug = val.toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 30);
    setCustomHandle(slug);
    setHandleAvailable(null);
    if (handleCheckRef.current) clearTimeout(handleCheckRef.current);
    if (slug.length < 2) return;
    setHandleChecking(true);
    handleCheckRef.current = setTimeout(async () => {
      try {
        const res = await fetch(`${CARDS_API}/cards/handle-available/${encodeURIComponent(slug)}`);
        const data = await res.json();
        setHandleAvailable(data.available ?? false);
      } catch { /* non-fatal */ }
      setHandleChecking(false);
    }, 400);
  }

  async function reExtract() {
    const allUrls = [...new Set([...urls, ...addMoreUrls])];
    if (allUrls.length === 0 && !addMoreResume && !resume) return;
    // Skip questions — answers already collected from first pass
    questionIndexRef.current = QUESTIONS.length;
    setQuestionIndex(QUESTIONS.length);
    jobDoneRef.current = false;
    setJobDone(false);
    pendingCardRef.current = null;
    setUrls(allUrls);
    setAddMoreUrls([]);
    setAddMoreInput("");
    setError(null);
    setPhase("working");
    const form = new FormData();
    allUrls.forEach(u => form.append("url", u));
    const resumeFile = addMoreResume || resume;
    if (resumeFile) form.append("resume", resumeFile);
    try {
      const res = await fetch(`${CARDS_API}/onboard/start`, { method: "POST", body: form });
      if (!res.ok) throw new Error((await res.text()) || `Status ${res.status}`);
      const data = await res.json();
      setJobId(data.job_id);
      pollRef.current = setInterval(() => pollJob(data.job_id), 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Re-extract failed");
      setPhase("error");
    }
  }

  async function fixAndReExtract(badUrl: string, goodUrl: string) {
    const corrected = /^https?:\/\//i.test(goodUrl) ? goodUrl : `https://${goodUrl}`;
    const next = [...new Set(urls.map(u => u === badUrl ? corrected : u)), ...addMoreUrls].filter(Boolean);
    setUrls(next);
    setUrlWarnings(prev => prev.filter(w => w.url !== badUrl));
    setFixingUrl(null);
    setFixUrlInput("");
    setAddMoreUrls([]);
    setAddMoreInput("");
    setError(null);
    setPhase("working");
    questionIndexRef.current = QUESTIONS.length;
    setQuestionIndex(QUESTIONS.length);
    jobDoneRef.current = false;
    setJobDone(false);
    pendingCardRef.current = null;
    const form = new FormData();
    next.forEach(u => form.append("url", u));
    const resumeFile = addMoreResume || resume;
    if (resumeFile) form.append("resume", resumeFile);
    try {
      const res = await fetch(`${CARDS_API}/onboard/start`, { method: "POST", body: form });
      if (!res.ok) throw new Error((await res.text()) || `Status ${res.status}`);
      const data = await res.json();
      setJobId(data.job_id);
      pollRef.current = setInterval(() => pollJob(data.job_id), 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Re-extract failed");
      setPhase("error");
    }
  }

  async function uploadPhoto(file: File) {
    setPhotoUploading(true);
    try {
      // Anonymous onboarding (not yet signed in) has nowhere RLS-safe to
      // write — fall back to a local preview, same as any other upload
      // failure below. Storage RLS scopes writes to the uploader's own
      // folder — see ZYND_DB_UNIFY_PLAN.md §5.5.
      if (!user) throw new Error("not signed in");
      const ext = file.name.split(".").pop()?.toLowerCase() || "jpg";
      const path = `${user.id}/${Date.now()}.${ext}`;
      const supabase = createClient();
      const { error } = await supabase.storage.from("avatars").upload(path, file, { upsert: true });
      if (error) throw error;
      const { data } = supabase.storage.from("avatars").getPublicUrl(path);
      if (data?.publicUrl) {
        updateCard({ identity: { ...card!.identity, avatar_url: data.publicUrl } });
        setShowPhotoInput(false);
        setPhotoUrlInput("");
      }
    } catch {
      // Fallback: use object URL (works for preview, lost on reload)
      const url = URL.createObjectURL(file);
      updateCard({ identity: { ...card!.identity, avatar_url: url } });
      setShowPhotoInput(false);
    } finally {
      setPhotoUploading(false);
    }
  }

  const liveHandle = published || (existingHandle && !editHandle ? existingHandle : null);
  const askingMemory = memoryStep === "ask" && !!liveHandle;

  // ── panel copy shifts with the phase; the panel itself never moves ──
  const panel =
    askingMemory
      ? {
          badge: "Optional · Memory",
          title: <>Add your<br />memory</>,
          body: "Paste a mem0, Zep, Letta, or supermemory key. We preview how the tile looks. Nothing goes on your public profile until you approve.",
        }
      : published
      ? {
          badge: "Your profile is live",
          title: <>You&apos;re<br />live</>,
          body: "Your AI-readable profile is published. Sign in to claim it so you can edit it anytime — or just share the link.",
        }
      : phase === "review"
      ? {
          badge: editHandle ? "Editing your card · Changes go live on save" : "Nothing is live yet · You approve",
          title: editHandle ? <>Edit<br />your card</> : <>Review<br />your card</>,
          body: editHandle
            ? "Make any changes below — your profile updates the moment you save."
            : "Every line came from what's public. Edit anything that reads wrong — publishing is the only step that makes it visible.",
        }
      : existingHandle && !editHandle
      ? {
          badge: "Your profile is live",
          title: <>You already<br />have a card</>,
          body: "Your profile is discoverable by AI agents. Edit it anytime or create a new one.",
        }
      : {
          badge: "AI-discoverable · You review first",
          title: <>Add your<br />profiles</>,
          body: "Paste links to your GitHub, LinkedIn, X, or any website. Zynd scrapes what's public and builds your card — you approve before anything goes live.",
        };

  return (
    <>
      <style>{ZC_CSS}</style>

      <div className={`zc-root ${FONT_VARS}`}>
        <div className="zc-shell">

          {/* ── header ── */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "20px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "9px", paddingLeft: "4px" }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/assets/zynd-logo.png" alt="Zynd" style={{ height: "20px", width: "auto", display: "block" }} />
              <span style={{ font: `600 16px/1 ${DISPLAY}`, color: T.ink, letterSpacing: "-.01em" }}>Zynd Profile</span>
            </div>
            <Link href="/directory" className="zc-back zc-dirlink"
              style={{ display: "flex", alignItems: "center", gap: "8px", font: `500 12px/1 ${SANS}`, letterSpacing: ".1em", color: T.muted, textDecoration: "none" }}>
              <span style={{ fontSize: "14px" }}>←</span> Directory
            </Link>
          </div>

          <div className="zc-grid">

            {/* ── purple promise panel ── */}
            <div className="zc-panel">
              <span style={{ position: "absolute", top: "18px", right: "18px", width: "13px", height: "13px", borderTop: "2px solid rgba(255,255,255,.6)", borderRight: "2px solid rgba(255,255,255,.6)" }} />

              <div className="zc-badge" style={{ display: "flex", alignItems: "center", gap: "8px", background: "rgba(255,255,255,.16)", border: "1px solid rgba(255,255,255,.34)", borderRadius: "999px", padding: "8px 15px", width: "fit-content" }}>
                <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "#fff", display: "block" }} />
                <span className="zc-badge-text" style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".14em", textTransform: "uppercase", color: "#fff" }}>{panel.badge}</span>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
                <h1 className="zc-panel-title" style={{ margin: 0 }}>{panel.title}</h1>
                <p style={{ font: `400 15px/1.65 ${SANS}`, color: T.onPanel, maxWidth: "352px", textWrap: "pretty", margin: 0 }}>{panel.body}</p>
              </div>

              <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: "12px" }}>
                <div style={{ height: "1px", background: "rgba(255,255,255,.28)" }} />
                <div className="zc-panel-live" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "16px" }}>
                  <ProgressRing percent={progressPercent(phase, jobDone, published)} />
                  <span style={{ font: `400 12px/1.5 ${SANS}`, color: T.onPanel }}>{liveHandle ? "Live at" : "Publishes at"}</span>
                  <span className="zc-handle-pill" style={{ font: `500 12px/1 ${MONO}`, color: "#fff", background: "rgba(255,255,255,.16)", borderRadius: "8px", padding: "7px 10px" }}>
                    zynd.ai/p/{liveHandle || (customHandle.length >= 2 ? customHandle : "you")}
                  </span>
                </div>
                <div style={{ font: `400 12px/1.5 ${SANS}`, color: T.onPanel2 }}>
                  {liveHandle ? "already discoverable" : "after your review"}
                </div>
              </div>
            </div>

            {/* ── right column ── */}
            <div className="zc-col">

              {/* ── POST-PUBLISH: you're live — claim it / view it ── */}
              {published && phase === "review" && (
                <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
                  {memoryStep === "ask" ? (
                  <div className="zc-card zc-step-card" style={{ padding: "30px 32px 28px", display: "flex", flexDirection: "column", minHeight: 0 }}>
                    <MemoryProviderOnboard
                      firstName={(card?.identity?.name || "You").split(" ")[0]}
                      handle={published}
                      tone="light"
                      onSkip={() => setMemoryStep("done")}
                      onImported={() => setMemoryStep("done")}
                    />
                  </div>
                  ) : (
                  <div className="zc-card zc-live-card" style={{ width: "100%", maxWidth: "480px", padding: "44px 40px 40px", display: "flex", flexDirection: "column", alignItems: "center", gap: "22px", textAlign: "center" }}>

                    <div style={{ width: "58px", height: "58px", borderRadius: "50%", background: T.accent, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                      <svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden>
                        <path d="M5 12.5 10 17.5 19 7" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>

                    <div style={{ display: "flex", flexDirection: "column", gap: "8px", alignItems: "center" }}>
                      <span style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".14em", textTransform: "uppercase", color: T.accentHi }}>Published</span>
                      <p style={{ font: `700 30px/1.15 ${DISPLAY}`, color: T.ink, letterSpacing: "-.03em", margin: 0 }}>
                        You&apos;re live
                      </p>
                      <div className="zc-live-pill" style={{ display: "flex", alignItems: "center", gap: "10px", background: T.surface, border: `1px solid ${T.border}`, borderRadius: "999px", padding: "10px 12px 10px 18px" }}>
                        <span className="zc-live-url" style={{ font: `500 14px/1 ${MONO}`, color: T.ink }}>zynd.ai/p/{published}</span>
                        <button type="button" className="zc-copy" onClick={() => { navigator.clipboard?.writeText(`https://zynd.ai/p/${published}`).catch(() => {}); setCopied(true); setTimeout(() => setCopied(false), 1600); }}
                          style={{ background: T.ink, color: "#fff", border: "none", borderRadius: "999px", padding: "7px 14px", font: `600 11px/1 ${MONO}`, letterSpacing: ".04em", cursor: "pointer", flexShrink: 0 }}>
                          {copied ? "Copied" : "Copy"}
                        </button>
                      </div>
                      <p style={{ font: `400 14px/1.6 ${SANS}`, color: T.soft, margin: 0, maxWidth: "340px" }}>
                        Discoverable by AI agents right now. Sign in to claim it so you can edit it anytime.
                      </p>
                    </div>

                    <div style={{ display: "flex", flexDirection: "column", gap: "10px", width: "100%" }}>
                      <a href={`/p/${published}`}
                        style={{ background: T.accent, color: "#fff", borderRadius: "14px", padding: "16px 22px", font: `600 15px/1 ${DISPLAY}`, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between", textDecoration: "none", letterSpacing: "-.01em", width: "100%", boxSizing: "border-box" }}>
                        View my profile <span style={{ font: `400 16px/1 ${SANS}` }}>→</span>
                      </a>
                      {!authenticated && (
                        <>
                          <div style={{ display: "flex", alignItems: "center", gap: "12px", marginTop: "8px" }}>
                            <div style={{ height: "1px", background: T.border, flex: 1 }} />
                            <span style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".14em", textTransform: "uppercase", color: T.faint }}>Claim it</span>
                            <div style={{ height: "1px", background: T.border, flex: 1 }} />
                          </div>
                          <button type="button" onClick={loginWithLinkedin}
                            style={{ width: "100%", background: T.accent, color: "#fff", border: "none", borderRadius: "14px", padding: "16px 22px", font: `600 15px/1 ${DISPLAY}`, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: "10px", letterSpacing: "-.01em" }}>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="#fff"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452z"/></svg>
                            Claim with LinkedIn
                          </button>
                          <p style={{ font: `400 12px/1.5 ${SANS}`, color: T.faint, margin: 0, textAlign: "center" }}>
                            Sign in, then paste any memory API key (mem0, Zep, Letta, supermemory). We detect the provider and preview key facts. Nothing is public until you approve.
                          </p>
                        </>
                      )}
                      {authenticated && (
                        <a href={`/p/${published}/edit`}
                          style={{ background: T.surface, color: T.ink, border: `1px solid ${T.border}`, borderRadius: "14px", padding: "16px 22px", font: `600 15px/1 ${DISPLAY}`, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between", textDecoration: "none", width: "100%", boxSizing: "border-box" }}>
                          Edit my card <span>→</span>
                        </a>
                      )}
                    </div>
                  </div>
                  )}
                </div>
              )}

              {/* ── AUTH: user already has a card ── */}
              {ready && authenticated && existingHandle && !editHandle && phase === "form" && (
                <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
                  {memoryStep === "ask" ? (
                    <div className="zc-card zc-step-card" style={{ padding: "30px 32px 28px", display: "flex", flexDirection: "column", minHeight: 0 }}>
                      <MemoryProviderOnboard
                        firstName={(user?.user_metadata?.full_name || user?.email || "You").toString().split(" ")[0]}
                        handle={existingHandle}
                        tone="light"
                        onSkip={() => setMemoryStep("done")}
                        onImported={() => setMemoryStep("done")}
                      />
                    </div>
                  ) : (
                  <div className="zc-card zc-step-card" style={{ padding: "30px 32px", display: "flex", flexDirection: "column", justifyContent: "center", gap: "16px" }}>
                    <div className="zc-question">
                      {existingPublished ? "Your card is live." : "Your card is not published yet."}
                    </div>
                    <p style={{ font: `400 15px/1.6 ${SANS}`, color: T.soft, margin: 0, maxWidth: "420px" }}>
                      {existingPublished
                        ? "Edit it anytime, share the link, or start a new one."
                        : "It was left in review by an earlier version of the flow. Edit and save it to publish."}
                    </p>
                    <div style={{ display: "flex", flexDirection: "column", gap: "10px", maxWidth: "400px", marginTop: "8px" }}>
                    <a href={`/p/${existingHandle}/edit`}
                      className="zc-cta"
                      style={{ background: T.accent, color: "#fff", borderRadius: "18px", padding: "18px 22px", font: `600 15px/1 ${DISPLAY}`, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between", textDecoration: "none", letterSpacing: "-.01em" }}>
                      {existingPublished ? "Edit my card" : "Finish publishing"} <span style={{ font: `400 16px/1 ${SANS}` }}>→</span>
                    </a>
                    {existingPublished && (
                      <a href={`/p/${existingHandle}`}
                        className="zc-ghost"
                        style={{ background: T.surface, color: T.ink, border: `1px solid ${T.border}`, borderRadius: "18px", padding: "16px 22px", font: `500 15px/1 ${SANS}`, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between", textDecoration: "none" }}>
                        View profile <span>↗</span>
                      </a>
                    )}
                    </div>
                  </div>
                  )}
                </div>
              )}

              {/* ── STEP 0 — paste links (only when authenticated + no existing card blocking) ── */}
              {(!existingHandle || editHandle) && phase === "form" && (
                <form onSubmit={startOnboard} style={{ display: "flex", flexDirection: "column", gap: "16px", flex: 1, minHeight: 0 }}>

                  {/* S08 claim-first: a published card already matches this LinkedIn */}
                  {claimCandidates.length > 0 && (
                    <div className="zc-card" style={{ padding: "18px 22px", borderLeft: `3px solid ${T.accent}` }}>
                      <div style={{ font: `600 15px/1.4 ${DISPLAY}`, color: T.ink }}>
                        We found a card that looks like yours
                      </div>
                      <p style={{ font: `400 13px/1.5 ${SANS}`, color: T.soft, margin: "6px 0 10px" }}>
                        It was assembled from public data and hasn&apos;t been claimed yet. Claiming it beats building a duplicate.
                      </p>
                      {claimCandidates.slice(0, 3).map((c) => (
                        <div key={c.handle} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, background: T.surface, border: `1px solid ${T.border}`, borderRadius: 12, padding: "10px 14px", marginBottom: 8 }}>
                          <div style={{ minWidth: 0 }}>
                            <div style={{ font: `600 14px/1.3 ${SANS}`, color: T.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</div>
                            {c.headline && <div style={{ font: `400 12px/1.3 ${SANS}`, color: T.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.headline}</div>}
                          </div>
                          <a href={`/p/${encodeURIComponent(c.handle)}`} className="zc-quick"
                            style={{ flexShrink: 0, background: T.ink, color: "#fff", borderRadius: "999px", padding: "8px 16px", font: `600 12px/1 ${MONO}`, textDecoration: "none" }}>
                            Is this you? →
                          </a>
                        </div>
                      ))}
                      <button type="button" className="zc-tap" onClick={() => setClaimCandidates([])}
                        style={{ background: "none", border: "none", padding: "2px 6px", cursor: "pointer", font: `400 12px/1 ${SANS}`, color: T.muted, textDecoration: "underline" }}>
                        No, build a new one
                      </button>
                    </div>
                  )}

                  {/* S08 auth-before-build: sign in now, no login wall after publish */}
                  {authNudge && !authenticated && (
                    <div className="zc-card" style={{ padding: "22px 24px", borderLeft: `3px solid ${T.accent}` }}>
                      <div style={{ font: `600 16px/1.4 ${DISPLAY}`, color: T.ink }}>Sign in before you build</div>
                      <p style={{ font: `400 13px/1.5 ${SANS}`, color: T.soft, margin: "6px 0 12px" }}>
                        With LinkedIn you can edit your card anytime and claim it the moment it publishes — no login wall afterwards.
                      </p>
                      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                        <button type="button" className="zc-primary" onClick={loginWithLinkedin}
                          style={{ background: T.accent, color: "#fff", border: "none", borderRadius: "14px", padding: "12px 20px", font: `600 14px/1 ${DISPLAY}`, cursor: "pointer" }}>
                          Sign in with LinkedIn
                        </button>
                        <button type="button" className="zc-ghost" onClick={() => { setAuthNudge(false); authNudgeRef.current = true; void startOnboard(new Event("submit") as unknown as React.FormEvent); }}
                          style={{ background: T.surface, color: T.ink, border: `1px solid ${T.border}`, borderRadius: "14px", padding: "12px 20px", font: `500 13px/1 ${SANS}`, cursor: "pointer" }}>
                          Continue without signing in
                        </button>
                      </div>
                    </div>
                  )}

                  {notice === "no-profile" && (
                    <div className="zc-card" style={{ padding: "16px 20px", borderLeft: `3px solid ${T.accent}` }}>
                      <div style={{ font: `600 14px/1.4 ${DISPLAY}`, color: T.ink }}>No profile card on this account</div>
                      <p style={{ font: `400 13px/1.5 ${SANS}`, color: T.soft, margin: "6px 0 0" }}>
                        We signed you in, but there&apos;s no living profile linked to this email yet. Create one below — it takes about a minute.
                      </p>
                    </div>
                  )}
                  {notice === "lookup-failed" && (
                    <div className="zc-card" style={{ padding: "16px 20px", borderLeft: "3px solid #C2401F" }}>
                      <div style={{ font: `600 14px/1.4 ${DISPLAY}`, color: T.ink }}>Couldn&apos;t check for an existing profile</div>
                      <p style={{ font: `400 13px/1.5 ${SANS}`, color: T.soft, margin: "6px 0 0" }}>
                        Sign-in worked, but we couldn&apos;t reach the cards service. You can create a profile below or try signing in again in a moment.
                      </p>
                    </div>
                  )}

                  <div className="zc-card" style={{ padding: "28px 28px 26px", display: "flex", flexDirection: "column", gap: "18px" }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "16px" }}>
                      <span style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".14em", textTransform: "uppercase", color: T.muted }}>Profiles</span>
                      <span style={{ font: `400 12px/1 ${SANS}`, color: T.muted }}>Space or Enter to add</span>
                    </div>

                    {urls.length > 0 && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
                        {urls.map(url => (
                          <div key={url} className="zc-chip-enter zc-chipbox" style={{ display: "flex", alignItems: "center", gap: "9px", background: T.accent, borderRadius: "999px", padding: "8px 13px" }}>
                            <span className="zc-clip" style={{ font: `500 12px/1 ${MONO}`, color: "#fff" }}>{shortenUrl(url)}</span>
                            <button type="button" className="zc-x" onClick={() => removeUrl(url)} aria-label={`Remove ${shortenUrl(url)}`}
                              style={{ font: `400 13px/1 ${SANS}`, color: "rgba(255,255,255,.7)", background: "none", border: "none", padding: 0, cursor: "pointer" }}>×</button>
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="zc-inputbox" onClick={() => inputRef.current?.focus()}
                      style={{
                        background: T.surface,
                        border: `1px solid ${inputFocused ? T.accent : T.border}`,
                        boxShadow: inputFocused ? "0 0 0 3px rgba(123,114,233,.12)" : "none",
                        borderRadius: "18px", padding: "22px", display: "flex", alignItems: "center", gap: "10px", cursor: "text",
                      }}>
                      <span style={{ width: "2px", height: "19px", background: T.accent, display: "block", flexShrink: 0 }} />
                      <input
                        ref={inputRef} type="text" value={inputVal}
                        onChange={e => setInputVal(e.target.value)}
                        onKeyDown={handleKeyDown} onPaste={handlePaste}
                        onFocus={() => setInputFocused(true)}
                        onBlur={() => { setInputFocused(false); if (inputVal.trim()) addUrl(inputVal); }}
                        placeholder={urls.length === 0 ? "github.com/you  or  linkedin.com/in/you" : "Add another URL…"}
                        style={{ flex: 1, minWidth: 0, border: "none", outline: "none", background: "transparent", font: `400 15px/1 ${MONO}`, color: T.ink }}
                      />
                    </div>

                    {urlError && (
                      <div style={{ font: `400 13px/1.4 ${SANS}`, color: "#C2401F", display: "flex", alignItems: "center", gap: "6px" }}>
                        <span>⚠</span> {urlError}
                      </div>
                    )}

                    <div style={{ display: "flex", gap: "9px", flexWrap: "wrap" }}>
                      {QUICK_ADD.map(({ kind, domain }) => (
                        <button key={kind} type="button" className="zc-quick"
                          onClick={() => { setInputVal(domain); inputRef.current?.focus(); }}
                          style={{ display: "flex", alignItems: "center", gap: "8px", background: T.surface, border: `1px solid ${T.border}`, borderRadius: "999px", padding: "9px 15px", cursor: "pointer", font: `500 13px/1 ${SANS}`, color: T.ink }}>
                          <KindSquare kind={kind} />
                          {CHIP[kind].label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="zc-card" style={{ padding: "28px", display: "flex", flexDirection: "column", gap: "16px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".14em", textTransform: "uppercase", color: T.muted }}>Résumé</span>
                      <span style={{ font: `400 12px/1 ${SANS}`, color: T.faint }}>— optional</span>
                    </div>
                    <div className="zc-drop" onClick={() => fileRef.current?.click()}
                      style={{ background: T.surface, border: `1px dashed ${resume ? T.accent : T.dashed}`, borderRadius: "18px", padding: "20px", display: "flex", alignItems: "center", gap: "11px", cursor: "pointer" }}>
                      <span style={{ font: `400 15px/1 ${SANS}`, color: T.muted }}>↑</span>
                      <span style={{ font: `400 15px/1 ${SANS}`, color: resume ? T.ink : T.soft, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {resume ? resume.name : "Upload PDF or DOCX"}
                      </span>
                      {resume && (
                        <button type="button" className="zc-tap zc-tap-end" onClick={e => { e.stopPropagation(); setResume(null); }} aria-label="Remove résumé"
                          style={{ marginLeft: "auto", font: `400 15px/1 ${SANS}`, color: T.muted, background: "none", border: "none", cursor: "pointer", padding: 0 }}>×</button>
                      )}
                    </div>
                    <input ref={fileRef} type="file" accept=".pdf,.docx,application/pdf" onChange={e => setResume(e.target.files?.[0] ?? null)} style={{ display: "none" }} />
                  </div>

                  <div className="zc-ctarow" style={{ marginTop: "auto" }}>
                    <button type="submit" disabled={!hasSource} className="zc-cta"
                      style={{
                        background: hasSource ? T.accent : T.ctaOffBg, borderRadius: "26px", border: "none",
                        padding: "26px 30px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: "20px",
                        cursor: hasSource ? "pointer" : "not-allowed", textAlign: "left", width: "100%",
                      }}>
                      <span style={{ font: `600 19px/1 ${DISPLAY}`, color: hasSource ? "#fff" : T.ctaOffInk, letterSpacing: "-.01em" }}>Build my card</span>
                      <span style={{ font: `400 19px/1 ${SANS}`, color: hasSource ? "#fff" : T.ctaOffInk }}>→</span>
                    </button>
                    <div className="zc-card" style={{ padding: "22px 24px", display: "flex", flexDirection: "column", justifyContent: "center", gap: "7px" }}>
                      <span style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".14em", textTransform: "uppercase", color: T.muted }}>Step</span>
                      <span style={{ font: `600 15px/1.3 ${DISPLAY}`, color: T.ink, letterSpacing: "-.01em" }}>1 of 2 — then review</span>
                    </div>
                  </div>
                </form>
              )}

              {/* ── STEPS 1–5 — questions ── */}
              {phase === "working" && (() => {
                const q = QUESTIONS[questionIndex];
                const isLast = questionIndex === QUESTIONS.length - 1;
                const isDone = questionIndex >= QUESTIONS.length;

                // handoff — every question answered, card still building
                if (isDone) {
                  return (
                    <div className="zc-card zc-step-card" style={{ padding: "30px", display: "flex", flexDirection: "column", gap: "26px", justifyContent: "center", alignItems: "flex-start" }}>
                      <span style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".14em", textTransform: "uppercase", color: T.muted }}>
                        {QUESTIONS.length} of {QUESTIONS.length}
                      </span>
                      <div className="zc-question" style={{ maxWidth: "520px" }}>
                        Building your card from your answers and the scrape.
                      </div>
                      <p style={{ font: `400 15px/1.65 ${SANS}`, color: T.soft, maxWidth: "440px", textWrap: "pretty", margin: 0 }}>
                        Nothing is published yet. You&apos;ll see the draft card next and can edit every line before it goes live.
                      </p>
                      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                        <span className="zc-spin" style={{ width: "18px", height: "18px", borderRadius: "50%", border: `2px solid ${T.dotOff}`, borderTopColor: T.accent, display: "block" }} />
                        <span style={{ font: `400 13px/1 ${SANS}`, color: T.muted }}>Finishing up…</span>
                      </div>
                      <button type="button" className="zc-ghost" onClick={retreatQuestion}
                        style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: "999px", padding: "14px 26px", font: `500 15px/1 ${SANS}`, color: T.soft, cursor: "pointer" }}>
                        ← Back
                      </button>
                    </div>
                  );
                }

                return (
                  <div className="zc-card zc-step-card" style={{ padding: "30px 30px 26px", display: "flex", flexDirection: "column", gap: "26px" }}>

                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "20px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "7px" }}>
                        {QUESTIONS.map((_, i) => (
                          <span key={i} style={{
                            display: "block", height: "6px", borderRadius: "999px",
                            width: i === questionIndex ? "22px" : "6px",
                            background: i <= questionIndex ? T.accent : T.dotOff,
                            transition: "width .25s, background .25s",
                          }} />
                        ))}
                      </div>
                      <span style={{ font: `500 12px/1 ${MONO}`, color: T.muted }}>{questionIndex + 1} of {QUESTIONS.length}</span>
                    </div>

                    <div className="zc-question">{q.label}</div>

                    {q.type === "chips" && q.options && (
                      <div className="zc-chips" style={{ display: "flex", flexWrap: "wrap", gap: "10px", alignItems: "center" }}>
                        {q.options.map(opt => {
                          const on = (selections[q.id] ?? new Set<string>()).has(opt);
                          return (
                            <button key={opt} type="button" className="zc-opt"
                              onClick={() => toggleOption(q.id, opt)}
                              style={{
                                borderRadius: "999px", padding: "12px 19px", font: `500 15px/1 ${SANS}`,
                                background: on ? T.accent : T.surface,
                                border: `1px solid ${on ? T.accent : T.border}`,
                                color: on ? "#fff" : T.ink,
                              }}>
                              {opt}
                            </button>
                          );
                        })}
                        {[...(selections[q.id] ?? new Set<string>())]
                          .filter(s => !q.options!.some(o => o.toLowerCase() === s.toLowerCase()))
                          .map(custom => (
                            <button key={custom} type="button" className="zc-opt"
                              onClick={() => toggleOption(q.id, custom)}
                              style={{
                                borderRadius: "999px", padding: "12px 16px", font: `500 15px/1 ${SANS}`,
                                background: T.accent, border: `1px solid ${T.accent}`, color: "#fff",
                                display: "inline-flex", alignItems: "center", gap: "8px",
                              }}>
                              {custom}
                              <span aria-hidden style={{ font: `400 15px/1 ${SANS}`, opacity: 0.8 }}>×</span>
                            </button>
                          ))}
                        <input
                          ref={el => { customRefs.current[q.id] = el; }}
                          type="text"
                          className="zc-custom-input"
                          value={customs[q.id] ?? ""}
                          onChange={e => setCustoms(p => {
                            const out = { ...p, [q.id]: e.target.value };
                            customsRef.current = out;
                            return out;
                          })}
                          placeholder="Type another…"
                          style={{
                            borderRadius: "999px", padding: "12px 19px", font: `400 15px/1 ${SANS}`,
                            background: T.surface,
                            border: `1px dashed ${customs[q.id] ? T.accent : T.dashed}`,
                            color: T.ink, outline: "none", width: "148px",
                            transition: "border-color .12s, width .2s",
                          }}
                          onFocus={e => (e.target.style.width = "200px")}
                          onBlur={e => (e.target.style.width = customs[q.id] ? "200px" : "148px")}
                          onKeyDown={e => {
                            if (e.key !== "Enter") return;
                            e.preventDefault();
                            commitDraft(q.id, q.options);
                          }}
                        />
                        <button type="button" className="zc-opt"
                          onClick={() => commitDraft(q.id, q.options)}
                          disabled={!(customs[q.id] ?? "").trim()}
                          aria-label="Add custom option"
                          style={{
                            borderRadius: "999px", width: "42px", height: "42px", padding: 0,
                            font: `600 20px/1 ${SANS}`,
                            background: (customs[q.id] ?? "").trim() ? T.accent : T.surface,
                            border: `1px solid ${(customs[q.id] ?? "").trim() ? T.accent : T.border}`,
                            color: (customs[q.id] ?? "").trim() ? "#fff" : T.faint,
                            cursor: (customs[q.id] ?? "").trim() ? "pointer" : "default",
                          }}>+</button>
                      </div>
                    )}

                    {q.type === "text" && q.id === "location" && (
                      <div style={{ display: "flex", flexDirection: "column", gap: "9px" }}>
                        <input
                          type="text"
                          value={locationInput}
                          onChange={e => setLocationInput(e.target.value)}
                          placeholder={pendingCardRef.current?.identity.location
                            ? `AI guessed: ${pendingCardRef.current.identity.location} — confirm or correct`
                            : "e.g. San Francisco, CA"}
                          autoFocus
                          className="zc-field zc-bigfield"
                          style={{
                            width: "100%", padding: "20px 22px", borderRadius: "18px",
                            border: `1px solid ${locationInput ? T.accent : T.border}`,
                            background: T.surface, color: T.ink, font: `400 15px/1 ${SANS}`,
                            outline: "none", boxSizing: "border-box", transition: "border-color .12s",
                          }}
                          onKeyDown={e => { if (e.key === "Enter") advanceQuestion(); }}
                        />
                        <span style={{ font: `400 12px/1 ${SANS}`, color: T.faint }}>
                          {pendingCardRef.current?.identity.location
                            ? "Pre-filled from your profiles — edit it if it's wrong."
                            : "optional — skip if you prefer"}
                        </span>
                      </div>
                    )}

                    {q.type === "text" && q.id === "booking" && (
                      <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
                        {[
                          { label: "Calendly", value: calendlyInput, set: setCalendlyInput, placeholder: "https://calendly.com/yourname" },
                          { label: "Google Calendar", value: googleCalInput, set: setGoogleCalInput, placeholder: "https://calendar.app.google/…" },
                        ].map((f, i) => (
                          <label key={f.label} style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                            <span style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".14em", textTransform: "uppercase", color: T.muted }}>{f.label}</span>
                            <input
                              type="url"
                              value={f.value}
                              onChange={e => f.set(e.target.value)}
                              placeholder={f.placeholder}
                              autoFocus={i === 0}
                              className="zc-field zc-bigfield"
                              style={{
                                width: "100%", padding: "20px 22px", borderRadius: "18px",
                                border: `1px solid ${f.value ? T.accent : T.border}`,
                                background: T.surface, color: T.ink, font: `400 15px/1 ${SANS}`,
                                outline: "none", boxSizing: "border-box", transition: "border-color .12s",
                              }}
                              onKeyDown={e => { if (e.key === "Enter") advanceQuestion(); }}
                            />
                          </label>
                        ))}
                        <span style={{ font: `400 12px/1.5 ${SANS}`, color: T.faint }}>
                          optional — add either or both. For Google Calendar, share your appointment schedule&apos;s booking page link.
                        </span>
                      </div>
                    )}

                    <div className="zc-navrow" style={{ marginTop: "auto", display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px" }}>
                      <button type="button" className="zc-ghost" onClick={retreatQuestion}
                        disabled={questionIndex === 0}
                        style={{
                          background: T.surface, border: `1px solid ${T.border}`, borderRadius: "999px",
                          padding: "14px 26px", font: `500 15px/1 ${SANS}`,
                          color: questionIndex === 0 ? T.faint : T.soft,
                          cursor: questionIndex === 0 ? "default" : "pointer",
                          visibility: questionIndex === 0 ? "hidden" : "visible",
                        }}>
                        ← Back
                      </button>
                      <div className="zc-navgroup" style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                        <button type="button" className="zc-ghost" onClick={onNext}
                          style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: "999px", padding: "14px 26px", font: `500 15px/1 ${SANS}`, color: T.soft, cursor: "pointer" }}>
                          Skip
                        </button>
                        <button type="button" className="zc-primary" onClick={onNext}
                          style={{ background: T.accent, border: "none", borderRadius: "999px", padding: "14px 26px", display: "flex", alignItems: "center", gap: "11px", font: `600 15px/1 ${DISPLAY}`, color: "#fff", cursor: "pointer" }}>
                          {isLast ? "Done" : "Next"} <span style={{ font: `400 15px/1 ${SANS}` }}>→</span>
                        </button>
                      </div>
                    </div>

                    {urls.length > 0 && (
                      <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                        <div style={{ height: "1px", background: T.border }} />
                        <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
                          {urls.map(url => (
                            <span key={url} className="zc-chipbox" style={{ display: "flex", alignItems: "center", gap: "8px", background: T.surface, border: `1px solid ${T.border}`, borderRadius: "999px", padding: "7px 12px" }}>
                              <KindSquare kind={detectKind(url)} size={11} />
                              <span className="zc-clip" style={{ font: `500 12px/1 ${MONO}`, color: T.soft }}>{shortenUrl(url)}</span>
                            </span>
                          ))}
                          <span style={{ font: `400 13px/1 ${SANS}`, color: jobDone ? T.accentHi : T.faint }}>
                            {jobDone ? "✓ scraped" : "scraping…"}
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })()}

              {/* ── EXISTS: publish found a card this person already has ── */}
              {phase === "exists" && existsHandle && (
                <div className="zc-card zc-step-card" style={{ padding: "30px", display: "flex", flexDirection: "column", gap: "18px", justifyContent: "center", alignItems: "flex-start" }}>
                  <div className="zc-question" style={{ maxWidth: "520px" }}>
                    {authenticated ? "You already have a card." : "This profile already has a card."}
                  </div>
                  <p style={{ font: `400 15px/1.65 ${SANS}`, color: T.soft, maxWidth: "460px", textWrap: "pretty", margin: 0 }}>
                    {authenticated
                      ? "Each person has one card, so this one wasn't published. Edit your existing card to add anything new."
                      : "A card for this GitHub or X profile already exists. If it's yours, open it and sign in with LinkedIn to claim it."}
                  </p>
                  <div style={{ display: "flex", flexDirection: "column", gap: "10px", width: "100%", maxWidth: "400px" }}>
                    {authenticated && (
                      <a href={`/p/${existsHandle}/edit`} className="zc-cta"
                        style={{ background: T.accent, color: "#fff", borderRadius: "18px", padding: "18px 22px", font: `600 15px/1 ${DISPLAY}`, display: "flex", alignItems: "center", justifyContent: "space-between", textDecoration: "none", letterSpacing: "-.01em" }}>
                        Edit my card <span style={{ font: `400 16px/1 ${SANS}` }}>→</span>
                      </a>
                    )}
                    <a href={`/p/${existsHandle}`} className="zc-ghost"
                      style={{ background: T.surface, color: T.ink, border: `1px solid ${T.border}`, borderRadius: "18px", padding: "16px 22px", font: `500 15px/1 ${SANS}`, display: "flex", alignItems: "center", justifyContent: "space-between", textDecoration: "none" }}>
                      {authenticated ? "View my card" : "Open the card"} <span>↗</span>
                    </a>
                  </div>
                </div>
              )}

              {/* ── ERROR ── */}
              {phase === "error" && (
                <div className="zc-card zc-step-card" style={{ padding: "30px", display: "flex", flexDirection: "column", gap: "22px", justifyContent: "center", alignItems: "flex-start" }}>
                  <span style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".14em", textTransform: "uppercase", color: "#C2401F" }}>Something broke</span>
                  <div className="zc-question" style={{ maxWidth: "520px" }}>That didn&apos;t go through.</div>
                  <p style={{ font: `400 15px/1.65 ${SANS}`, color: T.soft, maxWidth: "440px", textWrap: "pretty", margin: 0 }}>{error}</p>
                  <button type="button" className="zc-primary" onClick={() => setPhase("form")}
                    style={{ background: T.accent, border: "none", borderRadius: "999px", padding: "15px 28px", display: "flex", alignItems: "center", gap: "11px", font: `600 15px/1 ${DISPLAY}`, color: "#fff", cursor: "pointer" }}>
                    Start over <span style={{ font: `400 15px/1 ${SANS}` }}>↺</span>
                  </button>
                </div>
              )}

              {/* ── REVIEW ── */}
              {phase === "review" && card && !published && (
                <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>

                  {/* ── URL WARNINGS: shown inline so user can fix without losing scraped data ── */}
                  {urlWarnings.length > 0 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                      {urlWarnings.map(w => (
                        <div key={w.url} className="zc-card" style={{ padding: "18px 22px", borderLeft: `3px solid #C2401F`, display: "flex", flexDirection: "column", gap: "10px" }}>
                          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "12px" }}>
                            <div style={{ display: "flex", flexDirection: "column", gap: "4px", minWidth: 0 }}>
                              <span style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".12em", textTransform: "uppercase", color: "#C2401F" }}>
                                ⚠ Source not scraped
                              </span>
                              <span style={{ font: `400 13px/1.5 ${SANS}`, color: T.soft }}>{w.message}</span>
                              <span style={{ font: `400 12px/1 ${MONO}`, color: T.faint, wordBreak: "break-all" }}>{w.url}</span>
                            </div>
                            <button type="button" className="zc-rowbtn"
                              onClick={() => setUrlWarnings(p => p.filter(x => x.url !== w.url))}
                              aria-label="Dismiss warning">×</button>
                          </div>
                          {fixingUrl === w.url ? (
                            <div className="zc-fixrow" style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                              <input
                                type="text"
                                value={fixUrlInput}
                                autoFocus
                                onChange={e => setFixUrlInput(e.target.value)}
                                onKeyDown={e => {
                                  if (e.key === "Enter" && fixUrlInput.trim()) fixAndReExtract(w.url, fixUrlInput.trim());
                                  if (e.key === "Escape") { setFixingUrl(null); setFixUrlInput(""); }
                                }}
                                placeholder="Correct URL, e.g. github.com/yourhandle"
                                className="zc-field"
                                style={{ flex: 1, padding: "10px 14px", fontSize: "13px", border: `1px solid ${T.accent}`, borderRadius: "10px", background: T.surface, color: T.ink, outline: "none", fontFamily: MONO }}
                              />
                              <button type="button" className="zc-btn" disabled={!fixUrlInput.trim()}
                                onClick={() => { if (fixUrlInput.trim()) fixAndReExtract(w.url, fixUrlInput.trim()); }}
                                style={{ background: T.accent, color: "#fff", border: "none", borderRadius: "10px", padding: "10px 16px", font: `600 12px/1 ${SANS}`, cursor: fixUrlInput.trim() ? "pointer" : "not-allowed", opacity: fixUrlInput.trim() ? 1 : 0.5, flexShrink: 0 }}>
                                Re-scrape ↺
                              </button>
                              <button type="button" className="zc-btn" onClick={() => { setFixingUrl(null); setFixUrlInput(""); }}
                                style={{ background: "none", border: "none", padding: "10px 8px", font: `400 12px/1 ${SANS}`, color: T.faint, cursor: "pointer" }}>
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <button type="button" className="zc-btn"
                              onClick={() => { setFixingUrl(w.url); setFixUrlInput(""); }}
                              style={{ background: T.ink, color: "#fff", border: "none", borderRadius: "10px", padding: "10px 18px", font: `600 12px/1 ${DISPLAY}`, cursor: "pointer", width: "fit-content" }}>
                              Fix URL and re-scrape →
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="zc-card" style={{ padding: "28px", display: "flex", flexDirection: "column", gap: "20px" }}>
                    <SectionLabel label="Identity" />

                    {/* photo + outbound links */}
                    <div style={{ display: "flex", alignItems: "flex-start", gap: "14px" }}>
                      <div style={{ position: "relative", flexShrink: 0 }}>
                        <Avatar url={card.identity.avatar_url} name={card.identity.name} />
                        <button type="button" className="zc-pencil" aria-label="Change photo" onClick={() => { setShowPhotoInput(p => !p); setPhotoUrlInput(""); }}
                          style={{ position: "absolute", bottom: 0, right: 0, width: "22px", height: "22px", borderRadius: "50%", background: T.ink, border: `2px solid ${T.card}`, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer" }}>
                          <svg width="10" height="10" viewBox="0 0 16 16" fill="none"><path d="M11 2 14 5 5 14H2v-3L11 2z" stroke="#fff" strokeWidth="1.5" strokeLinejoin="round"/></svg>
                        </button>
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: "6px", minWidth: 0, flex: 1 }}>
                        <span style={{ font: `400 13px/1.4 ${SANS}`, color: T.soft }}>
                          {card.identity.avatar_url ? "Profile photo — from scraped sources" : "No photo found"}
                        </span>
                        <div className="zc-photo-actions" style={{ display: "flex", gap: "12px" }}>
                          <button type="button" className="zc-rowbtn" onClick={() => { setShowPhotoInput(p => !p); setPhotoUrlInput(""); }}>
                            {showPhotoInput ? "Cancel" : "Change photo"}
                          </button>
                          {card.identity.avatar_url && (
                            <button type="button" className="zc-rowbtn" onClick={() => updateCard({ identity: { ...card.identity, avatar_url: "" } })}>
                              Remove
                            </button>
                          )}
                        </div>

                        {showPhotoInput && (
                          <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginTop: "4px" }}>
                            <div style={{ display: "flex", gap: "8px" }}>
                              <input
                                type="url"
                                value={photoUrlInput}
                                onChange={e => setPhotoUrlInput(e.target.value)}
                                placeholder="Paste image URL…"
                                className="zc-field"
                                style={{ flex: 1, padding: "9px 13px", fontSize: "13px", border: `1px solid ${T.border}`, borderRadius: "10px", background: T.surface, color: T.ink, outline: "none", fontFamily: SANS }}
                                onKeyDown={e => {
                                  if (e.key === "Enter" && photoUrlInput.trim()) {
                                    updateCard({ identity: { ...card.identity, avatar_url: photoUrlInput.trim() } });
                                    setShowPhotoInput(false);
                                    setPhotoUrlInput("");
                                  }
                                }}
                              />
                              <button type="button" className="zc-btn" disabled={!photoUrlInput.trim()}
                                onClick={() => { updateCard({ identity: { ...card.identity, avatar_url: photoUrlInput.trim() } }); setShowPhotoInput(false); setPhotoUrlInput(""); }}
                                style={{ background: T.accent, color: "#fff", border: "none", borderRadius: "10px", padding: "9px 16px", font: `600 12px/1 ${SANS}`, cursor: photoUrlInput.trim() ? "pointer" : "not-allowed", opacity: photoUrlInput.trim() ? 1 : 0.5, flexShrink: 0 }}>
                                Set
                              </button>
                            </div>
                            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                              <div style={{ height: "1px", background: T.border, flex: 1 }} />
                              <span style={{ font: `400 11px/1 ${SANS}`, color: T.faint }}>or</span>
                              <div style={{ height: "1px", background: T.border, flex: 1 }} />
                            </div>
                            <button type="button" className="zc-btn" disabled={photoUploading} onClick={() => photoFileRef.current?.click()}
                              style={{ background: T.surface, color: T.soft, border: `1px dashed ${T.dashed}`, borderRadius: "10px", padding: "9px 14px", font: `500 12px/1 ${SANS}`, cursor: "pointer", textAlign: "center" }}>
                              {photoUploading ? "Uploading…" : "↑ Upload photo (JPG / PNG / WebP)"}
                            </button>
                            <input ref={photoFileRef} type="file" accept="image/*" style={{ display: "none" }}
                              onChange={e => { const f = e.target.files?.[0]; if (f) uploadPhoto(f); }} />
                          </div>
                        )}
                      </div>
                    </div>

                    {Object.entries(card.identity.links).some(([, v]) => v) && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
                        {Object.entries(card.identity.links).filter(([, v]) => v).map(([key, url]) => (
                          <span key={key} className="zc-chipbox" style={{ display: "flex", alignItems: "center", gap: "9px", background: T.surface, border: `1px solid ${T.border}`, borderRadius: "999px", padding: "8px 13px" }}>
                            <KindSquare kind={detectKind(url)} size={11} />
                            <span className="zc-clip" style={{ font: `500 12px/1 ${MONO}`, color: T.soft }}>{shortenUrl(url)}</span>
                            <button type="button" className="zc-rowbtn" aria-label={`Remove ${key} link`}
                              onClick={() => updateCard({ identity: { ...card.identity, links: { ...card.identity.links, [key]: "" } } })}>×</button>
                          </span>
                        ))}
                      </div>
                    )}

                    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                      <TextField label="Name" value={card.identity.name} onChange={v => updateCard({ identity: { ...card.identity, name: v } })} />
                      <TextField label="Headline" value={card.identity.headline} onChange={v => updateCard({ identity: { ...card.identity, headline: v } })} />
                      <TextField label="Location" value={card.identity.location} placeholder="e.g. San Francisco, CA" onChange={v => updateCard({ identity: { ...card.identity, location: v } })} />
                      {!editHandle && (
                        <div>
                          <div style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".14em", textTransform: "uppercase", color: T.muted, marginBottom: "9px" }}>
                            Profile URL <span style={{ font: `400 10px/1 ${SANS}`, textTransform: "none", letterSpacing: 0, color: T.faint }}>— optional, set your custom slug</span>
                          </div>
                          <div className="zc-handle-wrap" style={{ position: "relative" }}>
                            <div className="zc-handle-prefix" style={{ position: "absolute", left: "15px", top: "50%", transform: "translateY(-50%)", font: `400 14px/1 ${MONO}`, color: T.faint, pointerEvents: "none", whiteSpace: "nowrap" }}>
                              zynd.ai/p/
                            </div>
                            <input
                              type="text"
                              value={customHandle}
                              onChange={e => onCustomHandleChange(e.target.value)}
                              placeholder="your-handle"
                              className="zc-field zc-handle-input"
                              style={{
                                width: "100%", padding: "13px 15px 13px 98px",
                                fontSize: "15px", fontFamily: MONO,
                                border: `1px solid ${customHandle.length >= 2 ? (handleChecking ? T.border : handleAvailable === false ? "#C2401F" : handleAvailable === true ? "#16A34A" : T.border) : T.border}`,
                                borderRadius: "14px", background: T.surface, color: T.ink, outline: "none", boxSizing: "border-box",
                              }}
                            />
                            {customHandle.length >= 2 && (
                              <span className="zc-handle-status" style={{ position: "absolute", right: "14px", top: "50%", transform: "translateY(-50%)", font: `400 12px/1 ${SANS}`, color: handleChecking ? T.faint : handleAvailable === false ? "#C2401F" : handleAvailable === true ? "#16A34A" : T.faint }}>
                                {handleChecking ? "checking…" : handleAvailable === false ? "taken" : handleAvailable === true ? "available ✓" : ""}
                              </span>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="zc-card" style={{ padding: "28px", display: "flex", flexDirection: "column", gap: "20px" }}>
                    <SectionLabel label="About" />
                    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                      <div>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "12px" }}>
                          <span style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".14em", textTransform: "uppercase", color: T.muted }}>Summary</span>
                          <span style={{ font: `400 12px/1 ${SANS}`, color: T.faint }}>{card.summary.length} characters</span>
                        </div>
                        <div style={{ height: "9px" }} />
                        <AutoGrowTextArea
                          value={card.summary}
                          onChange={v => updateCard({ summary: v })}
                          minRows={4}
                          className="zc-field"
                          style={{
                            width: "100%", padding: "13px 15px", fontSize: "15px", lineHeight: 1.5,
                            border: `1px solid ${T.border}`, borderRadius: "14px",
                            background: T.surface, color: T.ink, outline: "none",
                            fontFamily: SANS, boxSizing: "border-box", resize: "none", overflowY: "hidden",
                            transition: "border-color .14s",
                          }}
                        />
                      </div>
                      <TextField label="Citation snippet" value={card.citation_snippet} rows={2} autoGrow onChange={v => updateCard({ citation_snippet: v })} />
                    </div>
                  </div>

                  <div className="zc-card" style={{ padding: "28px", display: "flex", flexDirection: "column", gap: "20px" }}>
                    <SectionLabel label="Skills" total={card.skills.length} />
                    <SkillsEditor skills={card.skills} onSkillsChange={skills => updateCard({ skills })} />
                  </div>

                  {card.projects.length > 0 && (() => {
                    const kept = card.projects.filter((pr, i) => !excluded.has(projectKey(pr, i))).length;
                    return (
                      <div className="zc-card" style={{ padding: "28px", display: "flex", flexDirection: "column", gap: "20px" }}>
                        <SectionLabel label="Projects" total={card.projects.length} kept={kept} />
                        <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                          {card.projects.map((pr: Project, i: number) => {
                            const key = projectKey(pr, i);
                            const off = excluded.has(key);
                            return (
                              <div key={key} className={`zc-row${off ? " off" : ""}`}>
                                <div className="zc-row-main" style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: "5px" }}>
                                  <div style={{ display: "flex", alignItems: "baseline", gap: "10px", flexWrap: "wrap" }}>
                                    <span style={{ font: `600 15px/1.2 ${DISPLAY}`, color: T.ink, letterSpacing: "-.01em" }}>{pr.name}</span>
                                    {pr.stars ? <span style={{ font: `400 12px/1 ${MONO}`, color: T.muted }}>★ {pr.stars}</span> : null}
                                    {(pr.tech ?? []).map(t => (
                                      <span key={t} style={{ font: `400 12px/1 ${MONO}`, color: T.faint }}>{t}</span>
                                    ))}
                                  </div>
                                  {pr.description && (
                                    <span className="zc-clamp1" style={{ font: `400 13px/1.5 ${SANS}`, color: T.soft }}>{pr.description}</span>
                                  )}
                                </div>
                                <button type="button" className="zc-rowbtn" onClick={() => toggleExcluded(key)}
                                  aria-label={off ? `Restore ${pr.name}` : `Remove ${pr.name}`}>
                                  {off ? "Restore" : "\u00d7"}
                                </button>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })()}

                  {card.writing_samples.length > 0 && (() => {
                    const kept = card.writing_samples.filter((_, i) => !excluded.has(sampleKey(i))).length;
                    return (
                      <div className="zc-card" style={{ padding: "28px", display: "flex", flexDirection: "column", gap: "20px" }}>
                        <SectionLabel label="Posts" total={card.writing_samples.length} kept={kept} />
                        <p style={{ font: `400 13px/1.5 ${SANS}`, color: T.soft, margin: 0 }}>
                          Scraped from your social profiles and published on your card. Remove anything you&apos;d rather not have quoted.
                        </p>
                        <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                          {card.writing_samples.map((w: WritingSample, i: number) => {
                            const key = sampleKey(i);
                            const off = excluded.has(key);
                            return (
                              <div key={key} className={`zc-row zc-row-post${off ? " off" : ""}`}>
                                <span className="zc-row-label" title={w.platform} style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".1em", textTransform: "uppercase", color: T.muted, paddingTop: "4px", flexShrink: 0, width: "60px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                  {w.platform}
                                </span>
                                <span className="zc-row-main zc-clamp2" style={{ flex: 1, minWidth: 0, font: `400 14px/1.5 ${SANS}`, color: T.ink }}>
                                  {w.excerpt}
                                </span>
                                <button type="button" className="zc-rowbtn" onClick={() => toggleExcluded(key)}
                                  aria-label={off ? "Restore post" : "Remove post"}>
                                  {off ? "Restore" : "\u00d7"}
                                </button>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })()}

                  {/* ── Add more sources ── */}
                  {!editHandle && (
                    <div className="zc-card" style={{ padding: "22px 24px", display: "flex", flexDirection: "column", gap: "14px" }}>
                      <div className="zc-headrow" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                        <span style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".14em", textTransform: "uppercase", color: T.muted }}>Add more sources</span>
                        <span style={{ font: `400 12px/1 ${SANS}`, color: T.faint }}>re-extract with additional profiles</span>
                      </div>

                      {addMoreUrls.length > 0 && (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
                          {addMoreUrls.map(url => (
                            <div key={url} className="zc-chipbox" style={{ display: "flex", alignItems: "center", gap: "8px", background: T.accent, borderRadius: "999px", padding: "7px 12px" }}>
                              <span className="zc-clip" style={{ font: `500 11px/1 ${MONO}`, color: "#fff" }}>{shortenUrl(url)}</span>
                              <button type="button" className="zc-x" aria-label={`Remove ${shortenUrl(url)}`} onClick={() => setAddMoreUrls(p => p.filter(u => u !== url))}
                                style={{ font: `400 13px/1 ${SANS}`, color: "rgba(255,255,255,.7)", background: "none", border: "none", padding: 0, cursor: "pointer" }}>×</button>
                            </div>
                          ))}
                        </div>
                      )}

                      <div className="zc-addrow" style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                        <div className="zc-addbox" style={{ flex: 1, display: "flex", alignItems: "center", gap: "8px", background: T.surface, border: `1px solid ${T.border}`, borderRadius: "12px", padding: "10px 14px" }}>
                          <input
                            ref={addMoreInputRef}
                            type="text"
                            value={addMoreInput}
                            onChange={e => setAddMoreInput(e.target.value)}
                            onKeyDown={e => {
                              if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                const v = addMoreInput.trim();
                                if (v) {
                                  const withProto = /^https?:\/\//i.test(v) ? v : `https://${v}`;
                                  if (!addMoreUrls.includes(withProto) && !urls.includes(withProto)) setAddMoreUrls(p => [...p, withProto]);
                                  setAddMoreInput("");
                                }
                              }
                            }}
                            placeholder="linkedin.com/in/you or github.com/you"
                            style={{ flex: 1, border: "none", outline: "none", background: "transparent", font: `400 13px/1 ${MONO}`, color: T.ink }}
                          />
                        </div>
                        <button type="button" className="zc-btn" onClick={() => addMoreFileRef.current?.click()}
                          style={{ background: addMoreResume ? T.accent : T.surface, color: addMoreResume ? "#fff" : T.soft, border: `1px solid ${addMoreResume ? T.accent : T.border}`, borderRadius: "12px", padding: "10px 14px", font: `500 12px/1 ${SANS}`, cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0 }}>
                          {addMoreResume ? `✓ ${addMoreResume.name.slice(0, 14)}…` : "↑ Resume"}
                        </button>
                        <input ref={addMoreFileRef} type="file" accept=".pdf,.docx,application/pdf" onChange={e => setAddMoreResume(e.target.files?.[0] ?? null)} style={{ display: "none" }} />
                      </div>

                      <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                        {QUICK_ADD.map(({ kind, domain }) => (
                          <button key={kind} type="button" className="zc-quick"
                            onClick={() => { setAddMoreInput(domain); addMoreInputRef.current?.focus(); }}
                            style={{ display: "flex", alignItems: "center", gap: "7px", background: T.surface, border: `1px solid ${T.border}`, borderRadius: "999px", padding: "7px 13px", cursor: "pointer", font: `500 12px/1 ${SANS}`, color: T.ink }}>
                            <KindSquare kind={kind} size={11} />
                            {CHIP[kind].label}
                          </button>
                        ))}
                      </div>

                      {(addMoreUrls.length > 0 || addMoreResume) && (
                        <button type="button" className="zc-btn" onClick={reExtract}
                          style={{ background: T.ink, color: "#fff", border: "none", borderRadius: "12px", padding: "12px 20px", font: `600 13px/1 ${DISPLAY}`, cursor: "pointer", display: "flex", alignItems: "center", gap: "10px", width: "fit-content", letterSpacing: "-.01em" }}>
                          Re-extract with these sources <span style={{ font: `400 14px/1 ${SANS}` }}>↺</span>
                        </button>
                      )}
                    </div>
                  )}

                  <div className="zc-ctarow">
                    <button type="button" onClick={publish} className="zc-cta"
                      style={{ background: T.accent, borderRadius: "26px", border: "none", padding: "26px 30px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: "20px", cursor: "pointer", textAlign: "left", width: "100%" }}>
                      <span style={{ font: `600 19px/1 ${DISPLAY}`, color: "#fff", letterSpacing: "-.01em" }}>Publish my card</span>
                      <span style={{ font: `400 19px/1 ${SANS}`, color: "#fff" }}>→</span>
                    </button>
                    <div className="zc-card" style={{ padding: "22px 24px", display: "flex", flexDirection: "column", justifyContent: "center", gap: "7px" }}>
                      <span style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".14em", textTransform: "uppercase", color: T.muted }}>Step</span>
                      <span style={{ font: `600 15px/1.3 ${DISPLAY}`, color: T.ink, letterSpacing: "-.01em" }}>2 of 2 — goes live</span>
                    </div>
                  </div>
                </div>
              )}

            </div>
          </div>

          {/* ── tagline footer row — inside shell, always visible ── */}
          <div className="zc-foot" style={{ marginTop: "auto", borderTop: `1px solid ${T.border}`, paddingTop: "20px", display: "flex", alignItems: "center", gap: "0", flexWrap: "wrap" }}>
            <div className="zc-foot-tag" style={{ flex: "0 0 auto", paddingRight: "32px", marginRight: "32px", borderRight: `1px solid ${T.border}` }}>
              <p style={{ font: `700 22px/1.1 ${DISPLAY}`, color: T.ink, letterSpacing: "-.03em", margin: 0, whiteSpace: "nowrap" }}>
                Your work,<br />discoverable by AI.
              </p>
            </div>
            <div className="zc-foot-steps" style={{ display: "flex", gap: "0", flex: 1, minWidth: 0 }}>
              {[
                { num: "01", label: "Add your profiles", desc: "GitHub · LinkedIn · X · any URL" },
                { num: "02", label: "We scrape the public web", desc: "No passwords, no permissions" },
                { num: "03", label: "You review and approve", desc: "Edit every line before it goes live" },
              ].map(({ num, label, desc }, i) => (
                <div key={num} className="zc-foot-step" style={{ flex: 1, minWidth: 0, paddingLeft: i > 0 ? "24px" : "0", borderLeft: i > 0 ? `1px solid ${T.border}` : "none", marginLeft: i > 0 ? "24px" : "0", display: "flex", flexDirection: "column", gap: "5px" }}>
                  <span style={{ font: `500 10px/1 ${MONO}`, letterSpacing: ".14em", color: T.faint }}>{num}</span>
                  <span style={{ font: `600 13px/1.3 ${DISPLAY}`, color: T.ink, letterSpacing: "-.01em" }}>{label}</span>
                  <span style={{ font: `400 12px/1.4 ${SANS}`, color: T.soft }}>{desc}</span>
                </div>
              ))}
            </div>
          </div>

        </div>
      </div>
    </>
  );
}

export default function CreateProfilePage() {
  return (
    <Suspense fallback={null}>
      <CreateProfilePageContent />
    </Suspense>
  );
}
