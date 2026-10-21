"use client";

import { Github, Linkedin, Loader2, RefreshCw } from "lucide-react";
import type { AgentProfileCard } from "@/lib/cards";
import { ContributionHeatmap } from "../contribution-heatmap";
import { CountUp } from "../count-up";
import { Card } from "./edit-ui";
import { safeUrl } from "./edit-form";

function isBlank(s: string | null | undefined): boolean {
  if (!s) return true;
  const low = s.toLowerCase().trim();
  return low === "" || low === "n/a" || low === "not specified" || low === "unknown" || low === "none";
}

function usernameFromUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  return url.replace(/\/+$/, "").split("/").pop() || null;
}

export function ImportedTab({ card, links, refreshing, disabled, onRefresh, onEditLinks }: {
  card: AgentProfileCard;
  links: Record<string, string>;
  refreshing: boolean;
  disabled?: boolean;
  onRefresh: () => void;
  onEditLinks: () => void;
}) {
  const githubUrl = safeUrl(links.github || card.identity.links?.github);
  const githubHandle = usernameFromUrl(githubUrl) || card.handle;
  const linkedinUrl = safeUrl(links.linkedin);
  const jobs = (card.work_experience ?? []).filter((j) => !!(j.title || j.company));
  const contributions = card.contribution_stats ?? null;
  const hasHeatmap = !!contributions && Array.isArray(contributions.levels) && contributions.levels.length > 0;
  const stats = [
    card.linkedin_stats?.connections != null && { label: "LinkedIn connections", value: card.linkedin_stats.connections },
    card.x_stats?.followers != null && { label: "X followers", value: card.x_stats.followers },
    card.github_stats?.total_repos != null && {
      label: githubUrl ? `GitHub repos · @${githubHandle}` : "GitHub repos", value: card.github_stats.total_repos, href: githubUrl,
    },
  ].filter(Boolean) as { label: string; value: number; href?: string | null }[];
  const addLinksHint = githubUrl || linkedinUrl
    ? <>Use Refresh above to import it.</>
    : <>Add your GitHub or LinkedIn link on the <button type="button" className="pe-btn-link" onClick={onEditLinks}>Profile tab</button>, then refresh.</>;

  return (
    <>
      <Card title="GitHub & LinkedIn" hint="Work history, projects and stats are pulled from these links. A refresh can take up to a minute."
        action={
          <button type="button" className="pe-btn pe-btn-secondary pe-btn-sm" onClick={onRefresh} disabled={refreshing || disabled}>
            {refreshing ? <Loader2 size={15} className="pe-spin" /> : <RefreshCw size={15} />}
            {refreshing ? "Refreshing…" : "Refresh GitHub & LinkedIn"}
          </button>
        }>
        <div className="pe-sources">
          <div className="pe-source">
            <Github size={18} />
            <div style={{ minWidth: 0 }}><b>GitHub</b><span>{githubUrl ? `@${githubHandle}` : "No link yet"}</span></div>
          </div>
          <div className="pe-source">
            <Linkedin size={18} />
            <div style={{ minWidth: 0 }}><b>LinkedIn</b><span>{linkedinUrl ? linkedinUrl.replace(/^https?:\/\/(www\.)?/, "") : "No link yet"}</span></div>
          </div>
        </div>
        {!githubUrl && !linkedinUrl && (
          <p className="pe-note" style={{ marginTop: 10 }}>
            Add them on the <button type="button" className="pe-btn-link" onClick={onEditLinks}>Profile tab</button> first.
          </p>
        )}
      </Card>

      <Card id="career" title="Work experience"
        hint={card.experience_years != null ? `${card.experience_years} years · from LinkedIn` : "From LinkedIn."}>
        {jobs.length > 0 ? (
          <div className="pe-list">
            {jobs.slice(0, 8).map((job, i) => (
              <div key={i} className="pe-item">
                {job.company_logo ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img className="pe-logo" src={job.company_logo} alt="" />
                ) : (
                  <div className="pe-logo">{(job.company || job.title || "?").charAt(0).toUpperCase()}</div>
                )}
                <div className="pe-item-main">
                  <div className="pe-item-title">{job.title}</div>
                  <div className="pe-item-sub">
                    {[job.company, [job.start_date, job.end_date].filter(Boolean).join(" – ")].filter(Boolean).join(" · ")}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : <p className="pe-empty">No work history yet. {addLinksHint}</p>}
      </Card>

      <Card id="projects" title="Projects" hint="From GitHub and LinkedIn.">
        {card.projects.length > 0 ? (
          <div className="pe-list">
            {card.projects.slice(0, 8).map((proj) => {
              const url = safeUrl(proj.url);
              return (
                <div key={proj.name} className="pe-item">
                  <div className="pe-item-main">
                    <div className="pe-item-title">{proj.name}</div>
                    {!isBlank(proj.description) && <div className="pe-item-sub">{proj.description}</div>}
                  </div>
                  {url && <a href={url} target="_blank" rel="noreferrer" className="pe-btn pe-btn-ghost pe-btn-sm">Open</a>}
                </div>
              );
            })}
          </div>
        ) : <p className="pe-empty">No projects yet. {addLinksHint}</p>}
      </Card>

      {(stats.length > 0 || hasHeatmap) && (
        <Card id="stats" title="Stats" hint="From your public profiles. Refresh above to update GitHub.">
          {stats.length > 0 && (
            <div className="pe-stats">
              {stats.map((s) => (
                <div key={s.label} className="pe-stat">
                  <b><CountUp value={s.value} /></b>
                  <span>{s.href ? <a href={s.href} target="_blank" rel="noreferrer">{s.label}</a> : s.label}</span>
                </div>
              ))}
            </div>
          )}
          {hasHeatmap && contributions && (
            <div className="pe-heatmap">
              <ContributionHeatmap levels={contributions.levels} year={contributions.year} total={contributions.total} avgPerDay={contributions.avg_per_day} />
            </div>
          )}
        </Card>
      )}
    </>
  );
}
