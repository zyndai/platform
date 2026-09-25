"use client";

import { useCallback, useEffect, useState } from "react";

import type { ResumeData } from "./resume-pdf";

/** Work history and projects get long — pre-select only the most recent few. */
const DEFAULT_PICKED = 3;

/**
 * Everything here is styled inline rather than with utility classes. globals.css
 * is unlayered, so its bare `h2` / `body` rules outrank `@layer utilities` — and
 * its `h2` rule sets `-webkit-text-fill-color: transparent`, which overrides
 * `color` no matter how it is applied. Inline styles on non-heading elements are
 * the only reliable way to paint text on this page.
 */
const SURFACE = "#F7F7F4";
const PANEL = "#EFEFEB";
const BORDER = "#E4E4DE";
const BORDER_SOFT = "#DEDED8";
const INK = "#0B0B0B";
const BODY = "#6E6E68";
const MUTED = "#8E8E88";
const FAINT = "#A8A8A2";
const SEP = "#D6D6D0";
const ACCENT = "#7B72E9";
const ACCENT_DEEP = "#6157DE";
const ACCENT_BG = "#EDEBFD";
const ACCENT_BORDER = "#C9C3FF";
const BOX_OFF_BORDER = "#CFCFC8";

/* Space Grotesk is loaded site-wide; the profile page loads the other two. */
const SANS = "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif";
const MONO = "'Space Mono', ui-monospace, monospace";
const DISPLAY = "'Space Grotesk', -apple-system, BlinkMacSystemFont, sans-serif";

const EYEBROW: React.CSSProperties = {
  font: `700 10px/1 ${MONO}`,
  letterSpacing: ".14em",
  textTransform: "uppercase",
  color: MUTED,
};

/** Keeps long descriptions from turning the list into a wall of text. */
const CLAMP_2: React.CSSProperties = {
  display: "-webkit-box",
  WebkitBoxOrient: "vertical",
  WebkitLineClamp: 2,
  overflow: "hidden",
};

function pickDefaults<T>(items: T[]): boolean[] {
  return items.map((_, i) => i < DEFAULT_PICKED);
}

function dateRange(job: ResumeData["work"][number]): string {
  const start = (job.start_date ?? "").trim();
  const end = (job.end_date ?? "").trim();
  if (start) return `${start} — ${end || "Present"}`;
  return end || (job.duration ?? "").trim();
}

/* ─── primitives ──────────────────────────────────────────────────────────── */

function Tick({ on }: { on: boolean }) {
  return (
    <span
      aria-hidden
      style={{
        flex: "none",
        marginTop: 1,
        width: 19,
        height: 19,
        borderRadius: 6,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: on ? ACCENT : SURFACE,
        border: `1.5px solid ${on ? ACCENT : BOX_OFF_BORDER}`,
        font: `700 11px/1 ${SANS}`,
        color: "#FFFFFF",
      }}
    >
      {on ? "✓" : ""}
    </span>
  );
}

function Row({
  on,
  onToggle,
  title,
  meta,
  note,
  align = "flex-start",
}: {
  on: boolean;
  onToggle: () => void;
  title: string;
  meta?: string;
  note?: string;
  align?: "center" | "flex-start";
}) {
  return (
    <div
      role="checkbox"
      aria-checked={on}
      tabIndex={0}
      onClick={onToggle}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onToggle();
        }
      }}
      style={{
        cursor: "pointer",
        display: "flex",
        alignItems: align,
        gap: 13,
        background: on ? ACCENT_BG : PANEL,
        border: `1px solid ${on ? ACCENT_BORDER : BORDER}`,
        borderRadius: 18,
        padding: "14px 17px",
        transition: "background .15s, border-color .15s",
      }}
    >
      <Tick on={on} />
      <span style={{ display: "flex", flexDirection: "column", gap: 5, minWidth: 0 }}>
        <span style={{ font: `600 14px/1.3 ${SANS}`, color: INK }}>{title}</span>
        {meta && <span style={{ font: `400 11.5px/1.35 ${MONO}`, color: MUTED }}>{meta}</span>}
        {note && <span style={{ font: `400 12.5px/1.6 ${SANS}`, color: BODY, ...CLAMP_2 }}>{note}</span>}
      </span>
    </div>
  );
}

function SectionHead({
  label,
  selected,
  total,
  onAll,
  onNone,
}: {
  label: string;
  selected: number;
  total: number;
  onAll: () => void;
  onNone: () => void;
}) {
  const link = (active: boolean): React.CSSProperties => ({
    cursor: "pointer",
    font: `700 11px/1 ${MONO}`,
    letterSpacing: ".06em",
    textTransform: "uppercase",
    color: active ? ACCENT_DEEP : MUTED,
    background: "none",
    // longhands only: React warns when a shorthand and a longhand for the same
    // property are both present on a style object
    borderTop: "none",
    borderRight: "none",
    borderLeft: "none",
    borderBottom: `1px solid ${active ? ACCENT_BORDER : BORDER_SOFT}`,
    padding: "0 0 2px",
  });

  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <span style={EYEBROW}>{label}</span>
        <span style={{ font: `400 11px/1 ${MONO}`, color: FAINT }}>{selected}/{total}</span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <button type="button" onClick={onAll} style={link(true)}>All</button>
        <span style={{ color: SEP }}>/</span>
        <button type="button" onClick={onNone} style={link(false)}>None</button>
      </div>
    </div>
  );
}

function Section({ children }: { children: React.ReactNode }) {
  return <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>{children}</div>;
}

/* ─── dialog ──────────────────────────────────────────────────────────────── */

export function ResumePicker({
  resume,
  handle,
  onClose,
}: {
  resume: ResumeData;
  handle: string;
  onClose: () => void;
}) {
  const hasSummary = Boolean(resume.summary && resume.summary.trim());

  const [includeSummary, setIncludeSummary] = useState(hasSummary);
  const [skills, setSkills] = useState<boolean[]>(() => resume.skills.map(() => true));
  const [work, setWork] = useState<boolean[]>(() => pickDefaults(resume.work));
  const [projects, setProjects] = useState<boolean[]>(() => pickDefaults(resume.projects));
  const [building, setBuilding] = useState(false);
  const [closeHover, setCloseHover] = useState(false);
  const [buildHover, setBuildHover] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const toggle = (setter: React.Dispatch<React.SetStateAction<boolean[]>>, i: number) =>
    setter((prev) => prev.map((v, j) => (j === i ? !v : v)));
  const setAll = (setter: React.Dispatch<React.SetStateAction<boolean[]>>, on: boolean) =>
    setter((prev) => prev.map(() => on));

  const count = (flags: boolean[]) => flags.filter(Boolean).length;

  const onDownload = useCallback(async () => {
    if (building) return;
    setBuilding(true);
    try {
      const { buildResumePdf } = await import("./resume-pdf");
      const blob = await buildResumePdf({
        ...resume,
        summary: includeSummary ? resume.summary : null,
        skills: resume.skills.filter((_, i) => skills[i]),
        work: resume.work.filter((_, i) => work[i]),
        projects: resume.projects.filter((_, i) => projects[i]),
      });
      const a = document.createElement("a");
      const pdfUrl = URL.createObjectURL(blob);
      a.href = pdfUrl;
      a.download = `${handle}-resume.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(pdfUrl), 1000);
      onClose();
    } finally {
      setBuilding(false);
    }
  }, [building, resume, includeSummary, skills, work, projects, handle, onClose]);

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <div style={{ position: "absolute", inset: 0, background: "rgba(11,11,11,.34)" }} onClick={onClose} aria-hidden />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Build resume"
        style={{
          position: "relative",
          width: "min(620px, 100%)",
          maxHeight: "min(720px, 100%)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          background: SURFACE,
          borderRadius: 28,
          boxShadow: "0 30px 80px rgba(11,11,11,.32)",
          fontFamily: SANS,
        }}
      >
        {/* header */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 20, padding: "24px 26px 20px", borderBottom: `1px solid ${BORDER}` }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            <div style={EYEBROW}>Build Resume</div>
            <div role="heading" aria-level={2} style={{ font: `700 26px/1.15 ${DISPLAY}`, color: INK, letterSpacing: "-.025em" }}>
              Choose what to include
            </div>
            <div style={{ font: `400 13px/1.5 ${SANS}`, color: BODY }}>
              Name, role, location and links are always included.
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            onMouseEnter={() => setCloseHover(true)}
            onMouseLeave={() => setCloseHover(false)}
            style={{
              cursor: "pointer",
              width: 34,
              height: 34,
              borderRadius: "50%",
              border: `1px solid ${closeHover ? INK : BORDER_SOFT}`,
              background: PANEL,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              font: `400 15px/1 ${SANS}`,
              color: closeHover ? INK : BODY,
              flex: "none",
              transition: "color .15s, border-color .15s",
            }}
          >
            ×
          </button>
        </div>

        {/* body */}
        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "22px 26px 26px", display: "flex", flexDirection: "column", gap: 22 }}>
          {hasSummary && (
            <Section>
              <div style={EYEBROW}>Summary</div>
              <Row
                on={includeSummary}
                onToggle={() => setIncludeSummary((v) => !v)}
                title="Include summary"
                note={resume.summary ?? undefined}
              />
            </Section>
          )}

          {resume.skills.length > 0 && (
            <Section>
              <SectionHead
                label="Skill Matrix"
                selected={count(skills)}
                total={skills.length}
                onAll={() => setAll(setSkills, true)}
                onNone={() => setAll(setSkills, false)}
              />
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {resume.skills.map((skill, i) => (
                  <button
                    key={`${skill.name}-${i}`}
                    type="button"
                    role="checkbox"
                    aria-checked={skills[i]}
                    onClick={() => toggle(setSkills, i)}
                    style={{
                      cursor: "pointer",
                      borderRadius: 999,
                      padding: "9px 15px",
                      font: `700 12.5px/1 ${MONO}`,
                      background: skills[i] ? ACCENT : SURFACE,
                      border: `1px solid ${skills[i] ? ACCENT : BORDER_SOFT}`,
                      color: skills[i] ? "#FFFFFF" : BODY,
                      transition: "background .15s, border-color .15s, color .15s",
                    }}
                  >
                    {skill.name}
                  </button>
                ))}
              </div>
            </Section>
          )}

          {resume.work.length > 0 && (
            <Section>
              <SectionHead
                label="Work Experience"
                selected={count(work)}
                total={work.length}
                onAll={() => setAll(setWork, true)}
                onNone={() => setAll(setWork, false)}
              />
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {resume.work.map((job, i) => (
                  <Row
                    key={`${job.title}-${job.company}-${i}`}
                    on={work[i]}
                    onToggle={() => toggle(setWork, i)}
                    title={job.title || job.company || "Role"}
                    meta={[job.company, dateRange(job)].filter(Boolean).join("  ·  ")}
                    align="center"
                  />
                ))}
              </div>
            </Section>
          )}

          {resume.projects.length > 0 && (
            <Section>
              <SectionHead
                label="Live in Production"
                selected={count(projects)}
                total={projects.length}
                onAll={() => setAll(setProjects, true)}
                onNone={() => setAll(setProjects, false)}
              />
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {resume.projects.map((proj, i) => (
                  <Row
                    key={`${proj.name}-${i}`}
                    on={projects[i]}
                    onToggle={() => toggle(setProjects, i)}
                    title={proj.name}
                    note={proj.description ?? undefined}
                  />
                ))}
              </div>
            </Section>
          )}
        </div>

        {/* footer */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, padding: "16px 26px", borderTop: `1px solid ${BORDER}`, background: PANEL }}>
          <span style={{ font: `400 11px/1.35 ${MONO}`, color: BODY }}>
            {count(work)} roles · {count(projects)} projects · {count(skills)} skills
          </span>
          <button
            type="button"
            onClick={onDownload}
            disabled={building}
            onMouseEnter={() => setBuildHover(true)}
            onMouseLeave={() => setBuildHover(false)}
            style={{
              cursor: building ? "default" : "pointer",
              background: buildHover && !building ? ACCENT_DEEP : ACCENT,
              borderRadius: 999,
              border: "none",
              padding: "13px 24px",
              display: "flex",
              alignItems: "center",
              gap: 10,
              font: `600 14px/1 ${DISPLAY}`,
              color: "#FFFFFF",
              opacity: building ? 0.7 : 1,
              flex: "none",
              transition: "background .15s",
            }}
          >
            <span style={{ font: `400 14px/1 ${SANS}` }}>↓</span>
            {building ? "Building PDF…" : "Download PDF"}
          </button>
        </div>
      </div>
    </div>
  );
}
