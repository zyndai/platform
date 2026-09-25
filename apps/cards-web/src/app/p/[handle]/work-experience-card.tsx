"use client";

import { useState } from "react";

export type WorkJob = {
  title: string;
  company: string;
  company_logo?: string;
  employment_type?: string;
  start_date?: string;
  end_date?: string;
  duration?: string;
  location?: string;
  description?: string;
};

function isCurrent(end?: string) {
  return /^(present|current|now)$/i.test((end || "").trim());
}

/** Known company → domain for favicon when scrape logo is missing/broken. */
const COMPANY_DOMAINS: Record<string, string> = {
  zynd: "zynd.ai",
  "zynd ai": "zynd.ai",
  avalanche: "avax.network",
  "snowball money": "snowball.money",
  "0xspace": "0xspace.io",
  "0x space": "0xspace.io",
  scaler: "scaler.com",
  google: "google.com",
  microsoft: "microsoft.com",
  amazon: "amazon.com",
  meta: "meta.com",
  apple: "apple.com",
  openai: "openai.com",
  anthropic: "anthropic.com",
};

function favicon(domain: string) {
  return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=128`;
}

function initialsImg(name: string): string {
  const letter = (name || "?").charAt(0).toUpperCase();
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><rect width="80" height="80" rx="14" fill="#0f172a"/><text x="40" y="44" text-anchor="middle" dominant-baseline="middle" fill="#fff" font-family="system-ui,sans-serif" font-size="34" font-weight="700">${letter}</text></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

/** Resolve durable logo URLs. Never leave clearbit/licdn as the only option. */
export function companyLogoSrcs(company: string, logo?: string): string[] {
  const out: string[] = [];
  const push = (u: string | null | undefined) => {
    if (u && !out.includes(u)) out.push(u);
  };

  if (logo) {
    try {
      const u = new URL(logo);
      if (u.protocol === "http:" || u.protocol === "https:") {
        if (u.hostname.includes("clearbit.com")) {
          const host = u.pathname.replace(/^\//, "").split("/")[0];
          if (host?.includes(".") && !/(^|\.)bit\.ly$/i.test(host)) push(favicon(host));
        } else if (!u.hostname.includes("licdn.com") && !u.hostname.includes("linkedin.com")) {
          push(logo);
        }
      }
    } catch {
      /* ignore bad url */
    }
  }

  const key = (company || "").trim().toLowerCase();
  const known = COMPANY_DOMAINS[key];
  if (known) push(favicon(known));

  const slug = key.replace(/[^a-z0-9]+/g, "");
  if (slug.length >= 3) push(favicon(`${slug}.com`));

  push(initialsImg(company));
  return out;
}

function JobLogo({ company, logo }: { company: string; logo?: string }) {
  const srcs = companyLogoSrcs(company, logo);
  const [i, setI] = useState(0);
  const src = srcs[Math.min(i, srcs.length - 1)];
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt=""
      width={40}
      height={40}
      referrerPolicy="no-referrer"
      onError={() => setI((n) => (n + 1 < srcs.length ? n + 1 : n))}
      style={{ width: 40, height: 40, borderRadius: 8, objectFit: "contain", flexShrink: 0, background: "#fff" }}
    />
  );
}

function JobRow({ job, first }: { job: WorkJob; first: boolean }) {
  const current = isCurrent(job.end_date);
  const when = [job.start_date, job.end_date || (current ? "Present" : "")].filter(Boolean).join(" – ");
  const whenDur = [when, job.duration].filter(Boolean).join(" · ");
  return (
    <div style={{ display: "flex", gap: 10, padding: "10px 0", borderTop: first ? "none" : "1px solid #f1f5f9" }}>
      <JobLogo company={job.company || job.title} logo={job.company_logo} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <div style={{ fontSize: "0.88rem", fontWeight: 700, color: "#191919", lineHeight: 1.25 }}>{job.title || job.company}</div>
          {current && (
            <span className="pf-mono" style={{ fontSize: "0.55rem", fontWeight: 700, letterSpacing: "0.06em", color: "#047857", background: "#d1fae5", borderRadius: 99, padding: "2px 7px" }}>CURRENT</span>
          )}
        </div>
        <div style={{ fontSize: "0.78rem", color: "#334155", fontWeight: 600, marginTop: 1 }}>
          {job.company}{job.employment_type ? ` · ${job.employment_type}` : ""}
        </div>
        {whenDur && (
          <div style={{ fontSize: "0.72rem", color: "#64748b", marginTop: 2 }}>{whenDur}</div>
        )}
      </div>
    </div>
  );
}

export function WorkExperienceCard({
  jobs,
  experienceYears,
  linkedinHandle,
  linkedinUrl,
  cardClass,
  labelClass,
  pillClass,
}: {
  jobs: WorkJob[];
  experienceYears: number | null | undefined;
  linkedinHandle: string | null;
  linkedinUrl: string | null;
  cardClass: string;
  labelClass: string;
  pillClass: string;
}) {
  const [showPast, setShowPast] = useState(false);
  const PREVIEW = 4;
  const ranked = [
    ...jobs.filter((j) => isCurrent(j.end_date)),
    ...jobs.filter((j) => !isCurrent(j.end_date)),
  ];
  const primary = ranked.slice(0, PREVIEW);
  const extra = ranked.slice(PREVIEW);
  const shown = showPast ? ranked : primary;
  const current = jobs.filter((j) => isCurrent(j.end_date));
  const expLabel = experienceYears != null
    ? `${experienceYears}Y EXP`
    : current.length > 0
      ? "CURRENT"
      : jobs.length > 0 ? `${jobs.length} ROLES` : "EXP";

  return (
    <div className={`${cardClass} tc pf-work`} style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div className={`${labelClass} pf-mono`} style={{ flexShrink: 0 }}>
        <span>┌ WORK EXPERIENCE</span>
        <span className={`${pillClass} text-indigo-600 bg-indigo-50 border-indigo-200`}>{expLabel} ┐</span>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
        {shown.length > 0 ? (
          shown.map((job, i) => (
            <JobRow key={`${job.company}-${job.title}-${i}`} job={job} first={i === 0} />
          ))
        ) : (
          <div className="pf-mono" style={{ fontSize: "0.75rem", color: "#94a3b8" }}>
            {linkedinHandle
              ? "LinkedIn connected — work history will appear after the next profile sync."
              : "Connect LinkedIn to import roles, dates, and companies."}
          </div>
        )}
      </div>
      <div style={{ flexShrink: 0, paddingTop: 8 }}>
        {extra.length > 0 && (
          <button
            type="button"
            onClick={() => setShowPast((v) => !v)}
            className="pf-mono"
            style={{ fontSize: "0.68rem", fontWeight: 700, color: "#4f46e5", background: "none", border: "none", padding: "6px 0", cursor: "pointer", textAlign: "left" }}
          >
            {showPast ? "Hide previous experience" : `See previous experience (${extra.length})`}
          </button>
        )}
        {linkedinHandle && (
          <div className="pf-mono" style={{ fontSize: "0.68rem", color: "#94a3b8", marginTop: extra.length > 0 ? 2 : 0 }}>
            {linkedinUrl ? <a href={linkedinUrl} target="_blank" rel="noreferrer">in/{linkedinHandle} ↗</a> : `in/${linkedinHandle}`}
          </div>
        )}
      </div>
    </div>
  );
}
