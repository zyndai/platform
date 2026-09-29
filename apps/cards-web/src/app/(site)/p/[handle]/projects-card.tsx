"use client";

import { SkillBrandIcon } from "./skill-icon";

type Project = {
  name: string;
  url?: string | null;
  description?: string | null;
  tech: string[];
  stars?: number | null;
};

function compact(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(n);
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

function GithubGlyph({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M12 .5C5.73.5.5 5.73.5 12c0 5.08 3.29 9.39 7.86 10.91.58.11.79-.25.79-.56 0-.28-.01-1.02-.02-2-3.2.7-3.88-1.54-3.88-1.54-.53-1.34-1.3-1.7-1.3-1.7-1.06-.73.08-.72.08-.72 1.17.08 1.79 1.2 1.79 1.2 1.04 1.78 2.73 1.27 3.4.97.11-.75.41-1.27.74-1.56-2.55-.29-5.23-1.28-5.23-5.68 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.04 0 0 .97-.31 3.18 1.18a11.1 11.1 0 0 1 5.8 0c2.21-1.49 3.18-1.18 3.18-1.18.63 1.58.23 2.75.11 3.04.74.81 1.19 1.84 1.19 3.1 0 4.41-2.69 5.39-5.25 5.67.42.36.79 1.08.79 2.18 0 1.57-.01 2.84-.01 3.23 0 .31.21.68.8.56A10.52 10.52 0 0 0 23.5 12C23.5 5.73 18.27.5 12 .5z" />
    </svg>
  );
}

const PREVIEW = 4;

export function ProjectsCard({
  projects,
  githubUrl,
  cardClass,
  labelClass,
  pillClass,
}: {
  projects: Project[];
  githubUrl: string | null;
  cardClass: string;
  labelClass: string;
  pillClass: string;
}) {
  const overflow = projects.length > PREVIEW;
  return (
    <div className={`${cardClass} tc`} style={{ justifyContent: "flex-start", alignSelf: "start", height: "auto" }}>
      <div className={`${labelClass} pf-mono`}>
        <span>┌ LIVE IN PRODUCTION</span>
        <span className={`${pillClass} text-indigo-600 bg-indigo-50 border-indigo-200`}>{projects.length} HIGHLIGHTS ┐</span>
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
          maxHeight: overflow ? 360 : undefined,
          overflowY: overflow ? "auto" : "visible",
          paddingRight: overflow ? 4 : 0,
        }}
      >
        {projects.map((proj) => {
          const url = safeUrl(proj.url);
          const desc = (proj.description || "").trim();
          return (
            <div key={proj.name} style={{ display: "flex", alignItems: "flex-start", gap: 12, background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 12, padding: "10px 12px" }}>
              {proj.tech[0] ? <SkillBrandIcon name={proj.tech[0]} size={28} /> : <GithubGlyph size={24} />}
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  {url ? (
                    <a href={url} target="_blank" rel="noreferrer" style={{ color: "#0f172a", fontWeight: 800, fontSize: "0.82rem" }} className="hover:underline">
                      {proj.name}
                    </a>
                  ) : (
                    <span style={{ color: "#0f172a", fontWeight: 800, fontSize: "0.82rem" }}>{proj.name}</span>
                  )}
                  {proj.stars != null && proj.stars > 0 && (
                    <span className="pf-mono" style={{ color: "#c2410c", fontSize: "0.58rem", fontWeight: 800 }}>★ {compact(proj.stars)}</span>
                  )}
                </div>
                {desc && (
                  <p className="pf-proj-desc" style={{ margin: "2px 0 0", fontSize: "0.7rem", color: "#64748b", lineHeight: 1.35, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{desc}</p>
                )}
                {proj.tech.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
                    {proj.tech.slice(0, 3).map((t) => (
                      <span key={t} className="pf-mono" style={{ display: "inline-flex", alignItems: "center", gap: 4, background: "#fff", border: "1px solid #e2e8f0", color: "#4338ca", fontSize: "0.55rem", padding: "2px 6px", borderRadius: 99, fontWeight: 700 }}>
                        <SkillBrandIcon name={t} size={12} />
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {overflow && (
        <div className="pf-mono" style={{ marginTop: 8, fontSize: "0.62rem", color: "#94a3b8", fontWeight: 700 }}>
          Scroll for {projects.length - PREVIEW} more
        </div>
      )}
      {githubUrl && (
        <a href={githubUrl} target="_blank" rel="noreferrer" className="pf-mono" style={{ display: "inline-block", marginTop: 10, fontSize: "0.68rem", fontWeight: 700, color: "#4f46e5" }}>
          View GitHub ↗
        </a>
      )}
    </div>
  );
}
