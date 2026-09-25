"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { Geist, Geist_Mono, Space_Grotesk } from "next/font/google";
import { Check, Loader2, RefreshCw, X, Zap } from "lucide-react";
import {
  type AgentProfileCard,
  updateCard,
  CARDS_API,
  githubLoginFromUrl,
  refreshCardGithub,
  refreshCardLinkedIn,
} from "@/lib/cards";
import { createClient } from "@/lib/supabase/client";
import { factLabel } from "@/lib/memory-facts";
import { MemoryProviderOnboard } from "@/components/memory/MemoryProviderOnboard";
import { ContributionHeatmap } from "../contribution-heatmap";
import { CountUp } from "../count-up";

const geist = Geist({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--pe-sans" });
const geistMono = Geist_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--pe-mono" });
const spaceGrotesk = Space_Grotesk({ subsets: ["latin"], weight: ["500", "600", "700"], variable: "--pe-display" });
const FONT_VARS = `${geist.variable} ${geistMono.variable} ${spaceGrotesk.variable}`;

const T = {
  page: "#E6E6E3",
  card: "#F7F7F4",
  field: "#EFEFEB",
  accent: "#7B72E9",
  accentHi: "#6157DE",
  ink: "#0B0B0B",
  soft: "#6E6E68",
  muted: "#8E8E88",
  border: "#DEDED8",
} as const;

function isBlank(s: string | null | undefined): boolean {
  if (!s) return true;
  const low = s.toLowerCase().trim();
  return low === "" || low === "n/a" || low === "not specified" || low === "unknown" || low === "none";
}

function safeUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const { protocol } = new URL(url);
    return protocol === "http:" || protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}

function usernameFromUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  return url.replace(/\/+$/, "").split("/").pop() || null;
}

function withDefaultLinks(entries: [string, string][]): [string, string][] {
  const map = new Map(entries.map(([p, u]) => [p.toLowerCase(), [p, u] as [string, string]]));
  for (const key of ["github", "linkedin", "x", "website"]) {
    if (!map.has(key)) map.set(key, [key, ""]);
  }
  return [...map.values()];
}

const LEVEL_LABELS: Record<string, string> = {
  expert: "Expert", advanced: "Advanced", intermediate: "Intermediate", beginner: "Beginner",
};

const INTERESTS: { key: "love_talking_about" | "working_on" | "connect_with"; label: string; hint: string }[] = [
  { key: "love_talking_about", label: "Love talking about", hint: "Topics" },
  { key: "working_on", label: "Working on", hint: "Projects" },
  { key: "connect_with", label: "Connect with", hint: "People" },
];

function TagInput({ tags, onChange, placeholder }: {
  tags: string[]; onChange: (t: string[]) => void; placeholder?: string;
}) {
  const [input, setInput] = useState("");
  function commit() {
    const v = input.trim();
    if (v && !tags.includes(v)) onChange([...tags, v]);
    setInput("");
  }
  return (
    <div className="pe-tags">
      {tags.map((t) => (
        <span key={t} className="pe-chip">
          <span className="truncate">{t}</span>
          <button type="button" onClick={() => onChange(tags.filter((x) => x !== t))} aria-label={`Remove ${t}`}>
            <X size={11} />
          </button>
        </span>
      ))}
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); } }}
        onBlur={commit}
        placeholder={placeholder ?? "Add, then Enter"}
      />
    </div>
  );
}

function Toast({ msg, type }: { msg: string; type: "ok" | "err" }) {
  return (
    <div className={`pe-toast ${type === "ok" ? "ok" : "err"}`}>
      {type === "ok" ? <Check size={14} /> : <X size={14} />}
      <span>{msg}</span>
    </div>
  );
}

interface Props { initialCard: AgentProfileCard; handle: string; token: string; }

export function EditProfileClient({ initialCard, handle, token }: Props) {
  const [draft, setDraft] = useState<AgentProfileCard>({ ...initialCard, status: "published" });
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: "ok" | "err" } | null>(null);
  const [memoryStatus, setMemoryStatus] = useState<"idle" | "loading" | "connected" | "disconnected">("idle");
  const [memoryFacts, setMemoryFacts] = useState<Array<Record<string, unknown>>>(
    (initialCard.zynd_memory ?? []) as Array<Record<string, unknown>>
  );
  const [memorySkipped, setMemorySkipped] = useState(false);
  const [showProviderImport, setShowProviderImport] = useState(false);

  function showToast(msg: string, type: "ok" | "err") {
    setToast({ msg, type });
  }

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3200);
    return () => clearTimeout(t);
  }, [toast]);

  async function save(updated: AgentProfileCard) {
    setSaving(true);
    const result = await updateCard(handle, { ...updated, status: "published" }, token);
    if (result) {
      setDraft({ ...result, status: "published" });
      showToast("Saved — your profile is live", "ok");
    } else {
      showToast("Save failed — try again", "err");
    }
    setSaving(false);
  }

  async function syncMemory() {
    setMemoryStatus("loading");
    try {
      const res = await fetch(
        `${CARDS_API}/cards/by-handle/${encodeURIComponent(handle)}/refresh-memory`,
        { method: "POST", headers: { Authorization: `Bearer ${token}` } },
      );
      const data = await res.json();
      if (data.zynd_memory && data.zynd_memory.length > 0) {
        setMemoryFacts(data.zynd_memory);
        setDraft((prev) => ({ ...prev, zynd_memory: data.zynd_memory }));
        setMemoryStatus("connected");
        showToast(`${data.zynd_memory.length} memory facts synced`, "ok");
      } else {
        setMemoryStatus("disconnected");
        showToast("No ZYND memory found for this account", "err");
      }
    } catch {
      setMemoryStatus("disconnected");
      showToast("Memory sync failed", "err");
    }
  }

  const [handleInput, setHandleInput] = useState(handle);
  const [handleAvail, setHandleAvail] = useState<boolean | null>(null);
  const [handleChecking, setHandleChecking] = useState(false);
  const handleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function onHandleChange(val: string) {
    const slug = val.toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 30);
    setHandleInput(slug);
    setHandleAvail(null);
    if (handleTimerRef.current) clearTimeout(handleTimerRef.current);
    if (slug.length < 2) {
      setHandleChecking(false);
      return;
    }
    setHandleChecking(true);
    handleTimerRef.current = setTimeout(async () => {
      try {
        const r = await fetch(`${CARDS_API}/cards/handle-available/${encodeURIComponent(slug)}`);
        const d = await r.json();
        setHandleAvail(slug === handle ? null : d.available);
      } catch {
        setHandleAvail(null);
      }
      setHandleChecking(false);
    }, 400);
  }

  async function saveHandle() {
    if (handleInput === handle) return;
    if (!handleAvail) {
      showToast("Choose an available handle first", "err");
      return;
    }
    setSaving(true);
    try {
      const res = await fetch(
        `${CARDS_API}/cards/by-handle/${encodeURIComponent(handle)}`,
        {
          method: "PATCH",
          headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
          body: JSON.stringify({ ...draft, status: "published", new_handle: handleInput }),
        },
      );
      if (res.ok) {
        showToast("Handle updated — redirecting", "ok");
        setTimeout(() => { window.location.href = `/p/${handleInput}/edit`; }, 1200);
      } else {
        showToast("Could not update handle", "err");
      }
    } catch {
      showToast("Network error", "err");
    }
    setSaving(false);
  }

  const avatarFileRef = useRef<HTMLInputElement>(null);
  const [avatarUploading, setAvatarUploading] = useState(false);

  async function uploadAvatar(file: File): Promise<string | null> {
    try {
      const supabase = createClient();
      const ext = file.name.split(".").pop() ?? "jpg";
      const path = `avatars/${handle}-${Date.now()}.${ext}`;
      const { error } = await supabase.storage.from("avatars").upload(path, file, { upsert: true });
      if (error) return URL.createObjectURL(file);
      const { data } = supabase.storage.from("avatars").getPublicUrl(path);
      return data.publicUrl;
    } catch {
      return URL.createObjectURL(file);
    }
  }

  const [hName, setHName] = useState(draft.identity.name);
  const [hHeadline, setHHeadline] = useState(draft.identity.headline);
  const [hLocation, setHLocation] = useState(draft.identity.location);
  const [hAvatar, setHAvatar] = useState(draft.identity.avatar_url);
  const [hLinks, setHLinks] = useState<[string, string][]>(
    withDefaultLinks(Object.entries(draft.identity.links ?? {}).map(([p, u]) => [p, u as string]))
  );
  const [sText, setSText] = useState(draft.summary);
  const [sAvail, setSAvail] = useState(draft.availability);
  const [sIndustries, setSIndustries] = useState(draft.industries);
  const [oWorking, setOWorking] = useState(draft.working_on);
  const [oConnect, setOConnect] = useState(draft.connect_with);
  const [oTalking, setOTalking] = useState(draft.love_talking_about);
  const [skillList, setSkillList] = useState(draft.skills);
  const [newSkillName, setNewSkillName] = useState("");
  const [newSkillLevel, setNewSkillLevel] = useState("intermediate");
  const [calInput, setCalInput] = useState(draft.calendly_url ?? "");

  function addSkill() {
    const name = newSkillName.trim();
    if (!name) return;
    setSkillList((prev) => [...prev, { name, level: newSkillLevel, evidence_count: 1 }]);
    setNewSkillName("");
  }

  const obsValue = (key: (typeof INTERESTS)[number]["key"]) =>
    key === "love_talking_about" ? oTalking : key === "working_on" ? oWorking : oConnect;
  const setObs = (key: (typeof INTERESTS)[number]["key"]) =>
    key === "love_talking_about" ? setOTalking : key === "working_on" ? setOWorking : setOConnect;

  function currentLinks(): Record<string, string> {
    return Object.fromEntries(hLinks.filter(([p, u]) => p.trim() && u.trim()));
  }

  function draftFromForm(base: AgentProfileCard): AgentProfileCard {
    return {
      ...base,
      identity: { ...base.identity, name: hName, headline: hHeadline, location: hLocation, avatar_url: hAvatar, links: currentLinks() },
      summary: sText,
      availability: sAvail,
      industries: sIndustries,
      working_on: oWorking,
      connect_with: oConnect,
      love_talking_about: oTalking,
      skills: skillList,
      calendly_url: calInput.trim() || null,
    };
  }

  async function saveAll() {
    await save(draftFromForm(draft));
  }

  async function refreshFromLinks() {
    const links = currentLinks();
    const linkedinUrl = links.linkedin || "";
    const githubHandle = links.github ? githubLoginFromUrl(links.github) : null;
    if (!linkedinUrl && !githubHandle) {
      showToast("Add a GitHub or LinkedIn URL first", "err");
      return;
    }
    setRefreshing(true);
    try {
      const saved = await updateCard(handle, { ...draftFromForm(draft), status: "published" }, token);
      if (saved) setDraft({ ...saved, status: "published" });

      const parts: string[] = [];
      const failures: string[] = [];
      let next = saved ?? draft;

      if (linkedinUrl) {
        try {
          const data = await refreshCardLinkedIn(handle, token, linkedinUrl);
          if (data.work_experience) {
            next = { ...next, work_experience: data.work_experience };
            parts.push("LinkedIn");
          }
        } catch (err) {
          failures.push(err instanceof Error ? err.message : "LinkedIn refresh failed");
        }
      }
      if (githubHandle) {
        try {
          const data = await refreshCardGithub(handle, token, githubHandle);
          next = {
            ...next,
            github_stats: data.github_stats ?? next.github_stats,
            contribution_stats: data.contribution_stats ?? next.contribution_stats,
          };
          parts.push("GitHub");
        } catch (err) {
          failures.push(err instanceof Error ? err.message : "GitHub refresh failed");
        }
      }

      setDraft({ ...next, status: "published" });
      if (parts.length > 0 && failures.length === 0) {
        showToast(`Updated ${parts.join(" & ")}`, "ok");
      } else if (parts.length > 0) {
        showToast(`Updated ${parts.join(" & ")}. ${failures[0]}`, "err");
      } else {
        showToast(failures[0] || "Refresh failed", "err");
      }
    } catch {
      showToast("Refresh failed", "err");
    } finally {
      setRefreshing(false);
    }
  }

  const initials = (hName || "?").split(/\s+/).map((p) => p[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
  const jobs = (draft.work_experience ?? []).filter((j) => !!(j.title || j.company));
  const githubUrl = safeUrl(hLinks.find(([p]) => p.toLowerCase() === "github")?.[1] || draft.identity.links?.github);
  const githubHandle = usernameFromUrl(githubUrl) || handle;
  const contributions = draft.contribution_stats ?? null;
  const visibleFacts = memoryFacts.map((fact) => {
    const predicate = typeof fact.predicate === "string" ? fact.predicate : "";
    const object = typeof fact.object === "string" ? fact.object.trim() : "";
    if (predicate && object) return factLabel({ predicate, object });
    for (const key of ["content", "value", "text", "description", "fact", "summary"]) {
      if (typeof fact[key] === "string" && (fact[key] as string).trim()) return fact[key] as string;
    }
    return null;
  }).filter((t): t is string => !!t);

  return (
    <>
      <style>{`
        .pe, .pe * { box-sizing: border-box; letter-spacing: normal; }
        .pe {
          font-family: var(--pe-sans), system-ui, sans-serif;
          color: ${T.ink};
          background: ${T.page};
          min-height: 100dvh;
          width: 100%;
          line-height: 1.45;
        }
        .pe h1, .pe h2, .pe h3, .pe p {
          margin: 0; text-align: left; text-transform: none;
          background: none !important; -webkit-text-fill-color: currentColor !important;
          background-clip: border-box !important; -webkit-background-clip: border-box !important;
          font-size: inherit; font-weight: inherit; line-height: inherit;
        }
        .pe a { color: inherit; text-decoration: none; }
        .pe button, .pe input, .pe textarea, .pe select {
          font-family: inherit; letter-spacing: normal; word-break: normal;
        }
        .pe-shell { max-width: 880px; margin: 0 auto; padding: 36px 24px 40px; }
        .pe-h1 {
          font-family: var(--pe-display), system-ui, sans-serif;
          font-size: 32px; font-weight: 700; letter-spacing: -0.03em; line-height: 1.1;
        }
        .pe-sub { font-size: 15px; color: ${T.soft}; margin-top: 6px; }
        .pe-sec {
          background: ${T.card};
          border: 1px solid ${T.border};
          border-radius: 22px;
          padding: 28px 28px 24px;
          min-width: 0;
        }
        .pe-sec + .pe-sec, .pe-stack > * + * { margin-top: 14px; }
        .pe-kicker {
          font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
          text-transform: uppercase; color: ${T.accent}; margin-bottom: 6px;
        }
        .pe-title {
          font-family: var(--pe-display), system-ui, sans-serif;
          font-size: 20px; font-weight: 650; letter-spacing: -0.02em;
        }
        .pe-help { font-size: 13px; color: ${T.muted}; margin-top: 4px; margin-bottom: 18px; }
        .pe-lab { display: block; font-size: 13px; font-weight: 600; color: ${T.soft}; margin-bottom: 8px; }
        .ei {
          width: 100%;
          background: #fff;
          border: 1px solid ${T.border};
          border-radius: 14px;
          padding: 13px 16px;
          font-size: 15px;
          color: ${T.ink};
          outline: none;
        }
        .ei:focus { border-color: ${T.accent}; box-shadow: 0 0 0 3px rgba(123,114,233,.15); }
        .pe-id { display: grid; grid-template-columns: 120px minmax(0,1fr); gap: 24px; align-items: start; }
        .pe-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
        .pe-fields .full { grid-column: 1 / -1; }
        .pe-avatar {
          width: 120px; height: 120px; border-radius: 22px; overflow: hidden;
          border: 1px solid ${T.border}; background: ${T.accent}; position: relative; padding: 0;
          cursor: pointer;
        }
        .pe-avatar img { width: 100%; height: 100%; object-fit: cover; display: block; }
        .pe-avatar span.ph {
          position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
          color: #fff; font-family: var(--pe-display), sans-serif; font-size: 36px; font-weight: 700;
        }
        .pe-avatar .chg {
          position: absolute; inset: auto 8px 8px 8px; background: rgba(11,11,11,.78); color: #fff;
          font-size: 12px; font-weight: 600; border-radius: 10px; padding: 6px 0; opacity: 0; transition: opacity .12s;
        }
        .pe-avatar:hover .chg, .pe-avatar:focus-visible .chg { opacity: 1; }
        .pe-link { display: grid; grid-template-columns: 128px minmax(0,1fr) 40px; gap: 8px; margin-bottom: 8px; align-items: center; }
        .pe-iconbtn {
          height: 48px; width: 40px; border: 1px solid ${T.border}; background: #fff; border-radius: 12px;
          color: ${T.muted}; cursor: pointer; display: inline-flex; align-items: center; justify-content: center;
        }
        .pe-iconbtn:hover { color: #b91c1c; border-color: #fecaca; }
        .pe-tags {
          display: flex; flex-wrap: wrap; gap: 8px; min-height: 48px; align-items: center;
          background: #fff; border: 1px solid ${T.border}; border-radius: 14px; padding: 8px 10px;
        }
        .pe-tags:focus-within { border-color: ${T.accent}; box-shadow: 0 0 0 3px rgba(123,114,233,.15); }
        .pe-tags input { flex: 1; min-width: 120px; border: 0; outline: none; background: transparent; font-size: 14px; padding: 6px 4px; }
        .pe-chip {
          display: inline-flex; align-items: center; gap: 6px; max-width: 100%;
          background: ${T.field}; color: ${T.ink}; border-radius: 999px; padding: 6px 10px 6px 12px; font-size: 13px; font-weight: 500;
        }
        .pe-chip button { border: 0; background: none; padding: 0; color: ${T.muted}; cursor: pointer; display: inline-flex; }
        .pe-chip button:hover { color: ${T.ink}; }
        .pe-split { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap: 14px; align-items: stretch; }
        .pe-list { display: flex; flex-direction: column; }
        .pe-job { display: flex; gap: 12px; padding: 12px 0; border-top: 1px solid ${T.border}; min-width: 0; }
        .pe-job:first-child { border-top: 0; padding-top: 0; }
        .pe-job img, .pe-job .mark {
          width: 40px; height: 40px; border-radius: 10px; object-fit: cover; flex-shrink: 0;
          border: 1px solid ${T.border}; background: ${T.ink}; color: #fff;
          display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 700;
        }
        .pe-skill {
          display: flex; align-items: center; gap: 10px; padding: 8px 0; border-top: 1px solid ${T.border};
        }
        .pe-skill:first-child { border-top: 0; padding-top: 0; }
        .pe-skill input { flex: 1; min-width: 0; border: 0; background: transparent; outline: none; font-size: 15px; font-weight: 500; }
        .pe-skill select {
          border: 1px solid ${T.border}; background: #fff; border-radius: 10px; padding: 8px 10px; font-size: 13px; color: ${T.soft};
        }
        .pe-metric {
          display: flex; justify-content: space-between; align-items: baseline; padding: 10px 0;
          border-top: 1px solid ${T.border}; font-size: 14px;
        }
        .pe-metric:first-child { border-top: 0; padding-top: 0; }
        .pe-metric b { font-size: 18px; font-weight: 650; letter-spacing: -0.02em; }
        .pe-ghost {
          background: none; border: 0; color: ${T.accent}; font-size: 14px; font-weight: 600; cursor: pointer; padding: 0;
        }
        .pe-ghost:hover { color: ${T.accentHi}; }
        .pe-primary {
          background: ${T.accent}; color: #fff; border: 0; border-radius: 16px; padding: 14px 22px;
          font-family: var(--pe-display), sans-serif; font-size: 15px; font-weight: 600; cursor: pointer;
          display: inline-flex; align-items: center; gap: 8px;
        }
        .pe-primary:hover:not(:disabled) { background: ${T.accentHi}; }
        .pe-primary:disabled { opacity: .55; cursor: default; }
        .pe-secondary {
          background: #fff; color: ${T.ink}; border: 1px solid ${T.border}; border-radius: 16px; padding: 14px 20px;
          font-size: 15px; font-weight: 600; cursor: pointer;
        }
        .pe-bar {
          position: sticky; bottom: 0; z-index: 40;
          margin: 18px -24px 0; padding: 16px 24px;
          background: rgba(230,230,227,.92); backdrop-filter: blur(12px);
          border-top: 1px solid ${T.border};
        }
        .pe-toast {
          position: fixed; bottom: 88px; left: 50%; transform: translateX(-50%); z-index: 50;
          display: inline-flex; align-items: center; gap: 8px; padding: 12px 18px; border-radius: 14px;
          font-size: 14px; font-weight: 600; box-shadow: 0 12px 40px rgba(11,11,11,.16);
        }
        .pe-toast.ok { background: ${T.ink}; color: #fff; }
        .pe-toast.err { background: #b91c1c; color: #fff; }
        .pe-mem { background: #fff; border: 1px solid ${T.border}; border-radius: 12px; padding: 10px 12px; font-size: 14px; color: ${T.soft}; }
        @media (max-width: 720px) {
          .pe-shell { padding: 20px 16px 28px; }
          .pe-sec { padding: 20px 18px; border-radius: 18px; }
          .pe-h1 { font-size: 26px; }
          .pe-id, .pe-fields, .pe-split, .pe-link { grid-template-columns: minmax(0,1fr); }
          .pe-fields .full { grid-column: auto; }
          .pe-bar { margin-left: -16px; margin-right: -16px; padding: 14px 16px; }
        }
      `}</style>

      {toast && <Toast msg={toast.msg} type={toast.type} />}

      <div className={`pe ${FONT_VARS}`}>
        <div className="pe-shell">
          <header style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 16, marginBottom: 28, flexWrap: "wrap" }}>
            <div>
              <div className="pe-h1">Edit profile</div>
              <p className="pe-sub">zynd.ai/p/{handle}</p>
            </div>
            <Link href={`/p/${handle}`} className="pe-secondary" style={{ textDecoration: "none" }}>View live</Link>
          </header>

          <div className="pe-stack">
            <section className="pe-sec">
              <div className="pe-kicker">Identity</div>
              <div className="pe-title">How you appear</div>
              <p className="pe-help">Name, photo, and the links people use to find you.</p>
              <div className="pe-id">
                <div>
                  <button type="button" className="pe-avatar" onClick={() => avatarFileRef.current?.click()} disabled={avatarUploading}>
                    {hAvatar ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={hAvatar} alt="" />
                    ) : <span className="ph">{initials}</span>}
                    <span className="chg">{avatarUploading ? "Uploading…" : "Change photo"}</span>
                  </button>
                  <input ref={avatarFileRef} type="file" accept="image/*" className="hidden"
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      setAvatarUploading(true);
                      const url = await uploadAvatar(file);
                      if (url) setHAvatar(url);
                      setAvatarUploading(false);
                    }} />
                </div>
                <div className="pe-fields">
                  <div>
                    <label className="pe-lab" htmlFor="pe-name">Full name</label>
                    <input id="pe-name" value={hName} onChange={(e) => setHName(e.target.value)} className="ei" placeholder="Your name" />
                  </div>
                  <div>
                    <label className="pe-lab" htmlFor="pe-loc">Location</label>
                    <input id="pe-loc" value={hLocation} onChange={(e) => setHLocation(e.target.value)} className="ei" placeholder="City, country" />
                  </div>
                  <div className="full">
                    <label className="pe-lab" htmlFor="pe-head">Headline</label>
                    <input id="pe-head" value={hHeadline} onChange={(e) => setHHeadline(e.target.value)} className="ei" placeholder="Role · what you do" />
                  </div>
                </div>
              </div>
              <div style={{ marginTop: 22 }}>
                <div className="pe-lab">Links</div>
                {hLinks.map(([p, u], i) => (
                  <div key={i} className="pe-link">
                    <input value={p} onChange={(e) => { const n = [...hLinks]; n[i] = [e.target.value, u]; setHLinks(n); }}
                      className="ei" placeholder="Platform" aria-label="Platform" />
                    <input value={u} onChange={(e) => { const n = [...hLinks]; n[i] = [p, e.target.value]; setHLinks(n); }}
                      className="ei" placeholder="https://" aria-label="URL" />
                    <button type="button" className="pe-iconbtn" onClick={() => setHLinks(hLinks.filter((_, j) => j !== i))} aria-label="Remove link">
                      <X size={16} />
                    </button>
                  </div>
                ))}
                <button type="button" className="pe-ghost" onClick={() => setHLinks([...hLinks, ["", ""]])}>+ Add link</button>
                <div style={{ marginTop: 20, paddingTop: 18, borderTop: `1px solid ${T.border}` }}>
                  <div className="pe-lab">If import missed data</div>
                  <p className="pe-help" style={{ marginBottom: 12 }}>
                    Save your GitHub or LinkedIn URL, then refresh. This re-fetches work history and GitHub stats — it can take up to a minute.
                  </p>
                  <button type="button" className="pe-secondary" onClick={refreshFromLinks} disabled={refreshing || saving}
                    style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                    {refreshing ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
                    {refreshing ? "Refreshing…" : "Refresh GitHub & LinkedIn"}
                  </button>
                </div>
              </div>
            </section>

            <section className="pe-sec">
              <div className="pe-kicker">About</div>
              <div className="pe-title">Summary</div>
              <p className="pe-help">A few sentences on what you do and who you want to meet.</p>
              <textarea value={sText} onChange={(e) => setSText(e.target.value)} rows={5} className="ei" style={{ resize: "vertical", minHeight: 120 }}
                placeholder="Write a short professional summary" />
              <div className="pe-fields" style={{ marginTop: 16 }}>
                <div>
                  <label className="pe-lab">Availability</label>
                  <input value={sAvail} onChange={(e) => setSAvail(e.target.value)} className="ei" placeholder="Full-time, consulting…" />
                </div>
                <div>
                  <label className="pe-lab">Industries</label>
                  <TagInput tags={sIndustries} onChange={setSIndustries} placeholder="Add an industry" />
                </div>
              </div>
            </section>

            <section className="pe-sec">
              <div className="pe-kicker">Signals</div>
              <div className="pe-title">Interests</div>
              <p className="pe-help">Shown as chips on your public card. Press Enter to add.</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                {INTERESTS.map((item) => (
                  <div key={item.key}>
                    <label className="pe-lab">{item.label}</label>
                    <TagInput tags={obsValue(item.key)} onChange={setObs(item.key)} placeholder={item.hint} />
                  </div>
                ))}
              </div>
            </section>

            <div className="pe-split">
              <section className="pe-sec">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
                  <div>
                    <div className="pe-kicker">Memory</div>
                    <div className="pe-title">ZYND Memory</div>
                  </div>
                  <button type="button" className="pe-ghost" onClick={syncMemory} disabled={memoryStatus === "loading"}>
                    {memoryStatus === "loading" ? "Syncing…" : "Sync"}
                  </button>
                </div>
                <p className="pe-help">Facts AI agents read when they work with you.</p>
                {visibleFacts.length > 0 ? (
                  <>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {visibleFacts.slice(0, 6).map((text, i) => <div key={i} className="pe-mem">{text}</div>)}
                    </div>
                    {showProviderImport ? (
                      <div style={{ marginTop: 16 }}>
                        <MemoryProviderOnboard firstName={(hName || "You").split(" ")[0]} handle={handle} tone="light" compact
                          onSkip={() => setShowProviderImport(false)}
                          onImported={(facts) => {
                            const snapshot = facts as Array<Record<string, unknown>>;
                            setMemoryFacts(snapshot);
                            setDraft((prev) => ({ ...prev, zynd_memory: snapshot }));
                            setMemoryStatus("connected");
                            setShowProviderImport(false);
                          }} />
                      </div>
                    ) : (
                      <button type="button" className="pe-ghost" style={{ marginTop: 14 }} onClick={() => setShowProviderImport(true)}>
                        Import from a memory key
                      </button>
                    )}
                  </>
                ) : !memorySkipped ? (
                  <MemoryProviderOnboard firstName={(hName || "You").split(" ")[0]} handle={handle} tone="light" compact
                    onSkip={() => setMemorySkipped(true)}
                    onImported={(facts) => {
                      const snapshot = facts as Array<Record<string, unknown>>;
                      setMemoryFacts(snapshot);
                      setDraft((prev) => ({ ...prev, zynd_memory: snapshot }));
                      setMemoryStatus("connected");
                    }} />
                ) : (
                  <div>
                    {memoryStatus === "disconnected" && <p className="pe-help">No memory found for this account yet.</p>}
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                      <button type="button" className="pe-primary" style={{ padding: "11px 16px", fontSize: 14 }} onClick={syncMemory} disabled={memoryStatus === "loading"}>
                        {memoryStatus === "loading" ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                        Sync from ZYND
                      </button>
                      <button type="button" className="pe-secondary" style={{ padding: "11px 16px", fontSize: 14 }} onClick={() => setMemorySkipped(false)}>
                        Paste a key
                      </button>
                    </div>
                  </div>
                )}
              </section>

              <section className="pe-sec">
                <div className="pe-kicker">Career</div>
                <div className="pe-title">Work experience</div>
                <p className="pe-help">
                  {draft.experience_years != null ? `${draft.experience_years} years · imported from LinkedIn` : "Imported from LinkedIn when a URL is set."}
                </p>
                {jobs.length > 0 ? (
                  <div className="pe-list">
                    {jobs.slice(0, 8).map((job, i) => (
                      <div key={i} className="pe-job">
                        {job.company_logo ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={job.company_logo} alt="" />
                        ) : (
                          <div className="mark">{(job.company || job.title || "?").charAt(0).toUpperCase()}</div>
                        )}
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 15, fontWeight: 600 }}>{job.title}</div>
                          <div style={{ fontSize: 13, color: T.muted, marginTop: 2 }}>
                            {[job.company, [job.start_date, job.end_date].filter(Boolean).join(" – ")].filter(Boolean).join(" · ")}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p style={{ fontSize: 14, color: T.muted }}>Add a LinkedIn URL above, then use Refresh GitHub &amp; LinkedIn.</p>
                )}
              </section>
            </div>

            <section className="pe-sec">
              <div className="pe-kicker">Craft</div>
              <div className="pe-title">Skills</div>
              <p className="pe-help">Listed on your public skill matrix.</p>
              {skillList.length > 0 && (
                <div className="pe-list" style={{ marginBottom: 14 }}>
                  {skillList.map((skill, i) => (
                    <div key={i} className="pe-skill">
                      <input value={skill.name} onChange={(e) => { const n = [...skillList]; n[i] = { ...n[i], name: e.target.value }; setSkillList(n); }} />
                      <select value={skill.level} onChange={(e) => { const n = [...skillList]; n[i] = { ...n[i], level: e.target.value }; setSkillList(n); }}>
                        {["expert", "advanced", "intermediate", "beginner"].map((l) => <option key={l} value={l}>{LEVEL_LABELS[l]}</option>)}
                      </select>
                      <button type="button" className="pe-iconbtn" style={{ height: 40 }} onClick={() => setSkillList(skillList.filter((_, j) => j !== i))} aria-label="Remove skill">
                        <X size={15} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <input value={newSkillName} onChange={(e) => setNewSkillName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSkill(); } }}
                  className="ei" style={{ flex: 1, minWidth: 180 }} placeholder="Add a skill" />
                <select value={newSkillLevel} onChange={(e) => setNewSkillLevel(e.target.value)} className="ei" style={{ width: "auto" }}>
                  {["expert", "advanced", "intermediate", "beginner"].map((l) => <option key={l} value={l}>{LEVEL_LABELS[l]}</option>)}
                </select>
                <button type="button" className="pe-secondary" style={{ padding: "12px 16px" }} onClick={addSkill}>Add</button>
              </div>
            </section>

            {(draft.linkedin_stats || draft.x_stats || draft.github_stats) && (
              <section className="pe-sec">
                <div className="pe-kicker">Presence</div>
                <div className="pe-title">Synced stats</div>
                <p className="pe-help">Pulled from public profiles. Re-create the card to refresh.</p>
                {draft.linkedin_stats?.connections != null && (
                  <div className="pe-metric"><span>LinkedIn connections</span><b><CountUp value={Number(draft.linkedin_stats.connections)} /></b></div>
                )}
                {draft.x_stats?.followers != null && (
                  <div className="pe-metric"><span>X followers</span><b><CountUp value={Number(draft.x_stats.followers)} /></b></div>
                )}
                {draft.github_stats?.total_repos != null && (
                  <div className="pe-metric">
                    <span>{githubUrl ? <a href={githubUrl} target="_blank" rel="noreferrer">GitHub @{githubHandle}</a> : "GitHub repositories"}</span>
                    <b><CountUp value={draft.github_stats.total_repos} /></b>
                  </div>
                )}
                {contributions && Array.isArray(contributions.levels) && contributions.levels.length > 0 && (
                  <div style={{ marginTop: 16 }}>
                    <ContributionHeatmap levels={contributions.levels} year={contributions.year} total={contributions.total} avgPerDay={contributions.avg_per_day} />
                  </div>
                )}
              </section>
            )}

            {draft.projects.length > 0 && (
              <section className="pe-sec">
                <div className="pe-kicker">Work</div>
                <div className="pe-title">Projects</div>
                <p className="pe-help">Extracted from GitHub and LinkedIn.</p>
                <div className="pe-list">
                  {draft.projects.slice(0, 8).map((proj) => {
                    const url = safeUrl(proj.url);
                    return (
                      <div key={proj.name} className="pe-job">
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div style={{ fontSize: 15, fontWeight: 600 }}>{proj.name}</div>
                          {!isBlank(proj.description) && <div style={{ fontSize: 13, color: T.muted, marginTop: 2 }}>{proj.description}</div>}
                        </div>
                        {url && <a href={url} target="_blank" rel="noreferrer" className="pe-ghost">Open</a>}
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            <section className="pe-sec">
              <div className="pe-kicker">Settings</div>
              <div className="pe-title">Booking &amp; URL</div>
              <p className="pe-help">Your public handle and a scheduling link, if you take meetings.</p>
              <div className="pe-fields">
                <div>
                  <label className="pe-lab">Booking link</label>
                  <input value={calInput} onChange={(e) => setCalInput(e.target.value)} className="ei" placeholder="https://calendly.com/…" />
                </div>
                <div>
                  <label className="pe-lab">Profile URL</label>
                  <div style={{ display: "flex", alignItems: "center", background: "#fff", border: `1px solid ${T.border}`, borderRadius: 14, overflow: "hidden" }}>
                    <span style={{ padding: "0 0 0 16px", fontSize: 14, color: T.muted, flexShrink: 0 }}>zynd.ai/p/</span>
                    <input value={handleInput} onChange={(e) => onHandleChange(e.target.value)}
                      style={{ flex: 1, minWidth: 0, border: 0, outline: "none", padding: "13px 12px 13px 0", fontSize: 15 }} placeholder="handle" />
                    <span style={{ paddingRight: 12 }}>
                      {handleChecking && <Loader2 size={14} className="animate-spin" style={{ color: T.muted }} />}
                      {!handleChecking && handleAvail === true && <Check size={14} style={{ color: "#15803d" }} />}
                      {!handleChecking && handleAvail === false && <X size={14} style={{ color: "#b91c1c" }} />}
                    </span>
                  </div>
                  {handleInput !== handle && (
                    <button type="button" className="pe-ghost" style={{ marginTop: 10 }} onClick={saveHandle} disabled={saving || handleAvail !== true}>
                      {handleAvail === false ? "That handle is taken" : "Save new handle"}
                    </button>
                  )}
                </div>
              </div>
            </section>
          </div>

          <div className="pe-bar">
            <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 10, maxWidth: 880, margin: "0 auto" }}>
              <Link href={`/p/${handle}`} className="pe-secondary">Cancel</Link>
              <button type="button" className="pe-primary" onClick={saveAll} disabled={saving}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />}
                {saving ? "Saving…" : "Save changes"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
