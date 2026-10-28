"use client";

import { RotateCcw, X } from "lucide-react";

import { imgProxyUrl } from "@/lib/avatar";
import type { AgentProfileCard, Project, WorkItem, WritingSample } from "@/lib/cards";
import { projectKey, sampleKey, workKey } from "./model";

/** What the card shows as proof depends on what the person linked: code, writing or visual work. */

const PLATFORM_LABEL: Record<string, string> = { x: "X", linkedin: "LinkedIn", substack: "Substack", medium: "Medium", blog: "Blog" };
const platformLabel = (platform: string) => PLATFORM_LABEL[platform.toLowerCase()] ?? platform;
const SOCIAL = new Set(["x", "linkedin", "twitter"]);

function Block({ title, note, hint, children }: { title: string; note?: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="cr-block" aria-label={title}>
      <div className="cr-block-head">
        <span className="dc-label">{title}</span>
        {note && <span className="cr-note">{note}</span>}
      </div>
      {hint && <div className="cr-sub">{hint}</div>}
      {children}
    </section>
  );
}

function RemoveButton({ off, what, onClick }: { off: boolean; what: string; onClick: () => void }) {
  return (
    <button type="button" className="cr-mini" onClick={onClick} aria-label={off ? `Restore ${what}` : `Remove ${what}`}>
      {off ? <><RotateCcw size={13} aria-hidden="true" /> Restore</> : <X size={15} aria-hidden="true" />}
    </button>
  );
}

type Toggle = { excluded: ReadonlySet<string>; onToggle: (key: string) => void };

export function GithubBlock({ stats }: { stats: NonNullable<AgentProfileCard["github_stats"]> }) {
  const facts = [
    stats.total_repos ? `${stats.total_repos} public repos` : "",
    stats.top_languages?.length ? stats.top_languages.slice(0, 4).join(", ") : "",
  ].filter(Boolean);
  if (facts.length === 0) return null;
  return (
    <Block title="GitHub" hint="Your activity graph and top repos show on your profile.">
      <div className="dc-chips">{facts.map((f) => <span key={f} className="dc-chip dc-chip-plain">{f}</span>)}</div>
    </Block>
  );
}

export function WritingBlock({ samples, excluded, onToggle }: { samples: WritingSample[] } & Toggle) {
  if (samples.length === 0) return null;
  const kept = samples.filter((w) => !excluded.has(sampleKey(w))).length;
  const title = samples.some((s) => !SOCIAL.has(s.platform.toLowerCase())) ? "Recent writing" : "Recent posts";
  return (
    <Block title={title} note={`${kept} of ${samples.length} will publish`} hint="Quoted on your card. Remove anything you'd rather not show.">
      <div className="cr-rows">
        {samples.map((w, i) => {
          const key = sampleKey(w);
          const off = excluded.has(key);
          return (
            <div key={`${key}|${i}`} className={`cr-row${off ? " is-off" : ""}`}>
              <span className="cr-row-tag">{platformLabel(w.platform)}</span>
              <div className="cr-row-main"><div className="cr-row-text">{w.excerpt}</div></div>
              <RemoveButton off={off} what="post" onClick={() => onToggle(key)} />
            </div>
          );
        })}
      </div>
    </Block>
  );
}

export function GalleryBlock({ items, excluded, onToggle }: { items: WorkItem[] } & Toggle) {
  if (items.length === 0) return null;
  const kept = items.filter((item) => !excluded.has(workKey(item))).length;
  return (
    <Block title="Work" note={`${kept} of ${items.length} will publish`} hint="Project covers from your portfolio, shown as a grid.">
      <ul className="cr-gallery">
        {items.map((item, i) => {
          const key = workKey(item);
          const off = excluded.has(key);
          return (
            <li key={`${key}|${i}`} className={`cr-tile${off ? " is-off" : ""}`}>
              {/* eslint-disable-next-line @next/next/no-img-element -- remote project covers, proxied; sizes are unknown */}
              <img src={imgProxyUrl(item.image_url)} alt={item.title} loading="lazy" />
              <span className="cr-tile-title">{item.title}</span>
              <button type="button" className="cr-tile-x" onClick={() => onToggle(key)} aria-label={off ? `Restore ${item.title}` : `Remove ${item.title}`}>
                {off ? <RotateCcw size={13} aria-hidden="true" /> : <X size={14} aria-hidden="true" />}
              </button>
            </li>
          );
        })}
      </ul>
    </Block>
  );
}

export function ProjectsBlock({ projects, excluded, onToggle }: { projects: Project[] } & Toggle) {
  if (projects.length === 0) return null;
  const kept = projects.filter((p) => !excluded.has(projectKey(p))).length;
  return (
    <Block title="Projects" note={`${kept} of ${projects.length} will publish`}>
      <div className="cr-rows">
        {projects.map((p, i) => {
          const key = projectKey(p);
          const off = excluded.has(key);
          return (
            <div key={`${key}|${i}`} className={`cr-row${off ? " is-off" : ""}`}>
              <div className="cr-row-main">
                <div className="cr-row-title">
                  {p.name}
                  {p.stars ? <span>★ {p.stars}</span> : null}
                  {(p.tech ?? []).map((t) => <span key={t}>{t}</span>)}
                </div>
                {p.description && <div className="cr-row-text">{p.description}</div>}
              </div>
              <RemoveButton off={off} what={p.name} onClick={() => onToggle(key)} />
            </div>
          );
        })}
      </div>
    </Block>
  );
}
