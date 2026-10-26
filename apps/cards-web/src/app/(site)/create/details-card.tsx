"use client";

import { useState } from "react";
import { Plus, RotateCcw, X } from "lucide-react";

import { AutoGrowTextArea } from "@/components/AutoGrowTextArea";
import { PersonAvatar } from "@/components/discover/person-avatar";
import { EditionPicker } from "@/components/editions/edition-picker";
import { imgProxyUrl } from "@/lib/avatar";
import type { AgentProfileCard, Project, WritingSample } from "@/lib/cards";
import { readEdition } from "@/lib/editions";
import { KindIcon } from "./kind-icon";
import { detectKind, projectKey, sampleKey, shortenUrl, type DraftEdits } from "./model";

const LEVEL_LABEL: Record<string, string> = { expert: "Expert", advanced: "Advanced", intermediate: "Intermediate", beginner: "Beginner" };

function SkillsEditor({ skills, onChange }: { skills: AgentProfileCard["skills"]; onChange: (skills: AgentProfileCard["skills"]) => void }) {
  const [draft, setDraft] = useState("");

  const add = (raw: string) => {
    const next = [...skills];
    for (const name of raw.split(",").map((p) => p.trim()).filter(Boolean)) {
      if (!next.some((s) => s.name.toLowerCase() === name.toLowerCase())) next.push({ name, level: "intermediate", evidence_count: 0 });
    }
    if (next.length !== skills.length) onChange(next);
    setDraft("");
  };

  return (
    <div className="cr-section">
      {skills.length > 0 && (
        <div className="cr-chips">
          {skills.map((s) => (
            <span key={s.name} className="cr-skill">
              {s.name}
              <em>{LEVEL_LABEL[s.level] ?? "Intermediate"}</em>
              <button type="button" aria-label={`Remove ${s.name}`} onClick={() => onChange(skills.filter((x) => x.name !== s.name))}>
                <X size={13} aria-hidden="true" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="cr-inline">
        <input
          className="cr-input" value={draft} aria-label="Add a skill"
          placeholder={skills.length ? "Add another skill" : "Add a skill, then Enter"}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(draft); } }}
          onBlur={() => { if (draft.trim()) add(draft); }}
        />
        <button type="button" className="dc-btn dc-btn-ghost" onClick={() => add(draft)} disabled={!draft.trim()}><Plus size={14} aria-hidden="true" /> Add</button>
      </div>
    </div>
  );
}

function Heading({ children, note }: { children: string; note?: string }) {
  return (
    <div className="cr-head">
      <div className="cr-h" style={{ fontSize: 16 }}>{children}</div>
      {note && <span className="cr-note">{note}</span>}
    </div>
  );
}

function Skeleton() {
  return (
    <div className="cr-section" aria-hidden="true">
      <div className="cr-skel" style={{ height: 46 }} />
      <div className="cr-skel" style={{ height: 46 }} />
      <div className="cr-skel" style={{ height: 96 }} />
      <div className="cr-skel" style={{ height: 36, width: "60%" }} />
    </div>
  );
}

/** The draft, every line editable. Nothing here is public until Publish. */
export function DetailsCard({ card, building, hasSource, onEdit, excluded, onToggleExcluded }: {
  card: AgentProfileCard | null;
  building: boolean;
  hasSource: boolean;
  onEdit: (patch: DraftEdits) => void;
  excluded: ReadonlySet<string>;
  onToggleExcluded: (key: string) => void;
}) {
  const links = card ? Object.entries(card.identity.links).filter(([, v]) => v) : [];

  return (
    <section className="cr-card" aria-labelledby="cr-details-h">
      <div className="cr-head">
        <div className="cr-head-title">
          <div id="cr-details-h" className="cr-h">Your card</div>
          <div className="cr-sub">Every line came from what&apos;s public. Edit anything that reads wrong. Nothing is live until you publish.</div>
        </div>
      </div>

      {!card && (building ? <Skeleton /> : (
        <div className="cr-empty">
          <div className="cr-sub">{hasSource ? "Your draft will appear here." : "Add a profile link above and your draft writes itself here."}</div>
        </div>
      ))}

      {card && (
        <>
          <div className="cr-section">
            <Heading>Identity</Heading>
            <div className="cr-photo">
              <PersonAvatar name={card.identity.name} src={imgProxyUrl(card.identity.avatar_url)} size={56} />
              <span className="cr-sub">{card.identity.avatar_url ? "Photo from your linked accounts" : "No photo found"}</span>
            </div>
            {links.length > 0 && (
              <div className="cr-links">
                {links.map(([key, url]) => (
                  <span key={key} className="dc-chip">
                    <KindIcon kind={detectKind(url)} size={14} />
                    {shortenUrl(url)}
                    <button type="button" aria-label={`Remove ${key} link`} onClick={() => onEdit({ links: { ...card.identity.links, [key]: "" } })}>
                      <X size={12} aria-hidden="true" />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="cr-fields">
              <label className="cr-field">
                <span className="dc-label">Name</span>
                <input className="cr-input" value={card.identity.name} onChange={(e) => onEdit({ name: e.target.value })} />
              </label>
              <label className="cr-field">
                <span className="dc-label">Headline</span>
                <input className="cr-input" value={card.identity.headline} onChange={(e) => onEdit({ headline: e.target.value })} />
              </label>
            </div>
          </div>

          <hr className="cr-divider" />

          <div className="cr-section">
            <Heading note={`${card.summary.length} characters`}>Summary</Heading>
            <AutoGrowTextArea value={card.summary} onChange={(v) => onEdit({ summary: v })} minRows={4} className="cr-input" ariaLabel="Summary" />
            <label className="cr-field">
              <span className="dc-label">Citation snippet</span>
              <AutoGrowTextArea value={card.citation_snippet} onChange={(v) => onEdit({ citation: v })} minRows={2} className="cr-input" ariaLabel="Citation snippet" />
            </label>
          </div>

          <hr className="cr-divider" />

          <div className="cr-section">
            <Heading note={`${card.skills.length} ${card.skills.length === 1 ? "skill" : "skills"}`}>Skills</Heading>
            <SkillsEditor skills={card.skills} onChange={(skills) => onEdit({ skills })} />
          </div>

          {card.projects.length > 0 && (
            <>
              <hr className="cr-divider" />
              <div className="cr-section">
                <Heading note={`${card.projects.filter((p, i) => !excluded.has(projectKey(p, i))).length} of ${card.projects.length} will publish`}>Projects</Heading>
                <div className="cr-rows">
                  {card.projects.map((p: Project, i: number) => {
                    const key = projectKey(p, i);
                    const off = excluded.has(key);
                    return (
                      <div key={key} className={`cr-row${off ? " is-off" : ""}`}>
                        <div className="cr-row-main">
                          <div className="cr-row-title">
                            {p.name}
                            {p.stars ? <span>★ {p.stars}</span> : null}
                            {(p.tech ?? []).map((t) => <span key={t}>{t}</span>)}
                          </div>
                          {p.description && <div className="cr-row-text">{p.description}</div>}
                        </div>
                        <button type="button" className="cr-mini" onClick={() => onToggleExcluded(key)} aria-label={off ? `Restore ${p.name}` : `Remove ${p.name}`}>
                          {off ? <><RotateCcw size={13} aria-hidden="true" /> Restore</> : <X size={15} aria-hidden="true" />}
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            </>
          )}

          {card.writing_samples.length > 0 && (
            <>
              <hr className="cr-divider" />
              <div className="cr-section">
                <Heading note={`${card.writing_samples.filter((_, i) => !excluded.has(sampleKey(i))).length} of ${card.writing_samples.length} will publish`}>Posts</Heading>
                <div className="cr-sub">Pulled from your social profiles and quoted on your card. Remove anything you&apos;d rather not show.</div>
                <div className="cr-rows">
                  {card.writing_samples.map((w: WritingSample, i: number) => {
                    const key = sampleKey(i);
                    const off = excluded.has(key);
                    return (
                      <div key={key} className={`cr-row${off ? " is-off" : ""}`}>
                        <span className="cr-row-tag">{w.platform}</span>
                        <div className="cr-row-main"><div className="cr-row-text">{w.excerpt}</div></div>
                        <button type="button" className="cr-mini" onClick={() => onToggleExcluded(key)} aria-label={off ? "Restore post" : "Remove post"}>
                          {off ? <><RotateCcw size={13} aria-hidden="true" /> Restore</> : <X size={15} aria-hidden="true" />}
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            </>
          )}

          <hr className="cr-divider" />

          <div className="cr-section">
            <Heading>Card style</Heading>
            <EditionPicker
              value={readEdition(card.identity.edition)}
              onChange={(next) => onEdit({ edition: next })}
              person={{ name: card.identity.name, headline: card.identity.headline, avatarSrc: imgProxyUrl(card.identity.avatar_url) ?? null }}
            />
          </div>
        </>
      )}
    </section>
  );
}
