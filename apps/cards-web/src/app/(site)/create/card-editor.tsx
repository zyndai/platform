"use client";

import { useState } from "react";
import { MapPin, Plus, X } from "lucide-react";

import { AutoGrowTextArea } from "@/components/AutoGrowTextArea";
import { PersonAvatar } from "@/components/discover/person-avatar";
import { EditionPicker } from "@/components/editions/edition-picker";
import { imgProxyUrl } from "@/lib/avatar";
import type { AgentProfileCard } from "@/lib/cards";
import { readEdition } from "@/lib/editions";
import { ChipField } from "./chip-field";
import { CHIP_GROUPS, PERSONAS, optionsFor, type ChipGroupId, type PersonaId, type Selections } from "./chips";
import { InlineArea, InlineText } from "./inline";
import { KindIcon } from "./kind-icon";
import { detectKind, shortenUrl, type DraftEdits, type LiveIdentity } from "./model";
import { GalleryBlock, GithubBlock, ProjectsBlock, WritingBlock } from "./proof-blocks";

const LEVEL_LABEL: Record<string, string> = { expert: "Expert", advanced: "Advanced", intermediate: "Intermediate", beginner: "Beginner" };

function SkillsField({ skills, onAdd, onRemove }: {
  skills: AgentProfileCard["skills"];
  onAdd: (names: string[]) => void;
  onRemove: (name: string) => void;
}) {
  const [draft, setDraft] = useState("");

  const add = (raw: string) => {
    const have = new Set(skills.map((s) => s.name.toLowerCase()));
    const names: string[] = [];
    for (const name of raw.split(",").map((p) => p.trim()).filter(Boolean)) {
      if (!have.has(name.toLowerCase())) { have.add(name.toLowerCase()); names.push(name); }
    }
    if (names.length) onAdd(names);
    setDraft("");
  };

  return (
    <div className="cr-chips">
      {skills.map((s) => (
        <span key={s.name} className="cr-pick">
          {s.name}
          <em>{LEVEL_LABEL[s.level] ?? "Intermediate"}</em>
          <button type="button" aria-label={`Remove ${s.name}`} onClick={() => onRemove(s.name)}>
            <X size={13} aria-hidden="true" />
          </button>
        </span>
      ))}
      <span className="cr-add">
        <input
          value={draft} placeholder="Add a skill" aria-label="Add a skill"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(draft); } }}
          onBlur={() => { if (draft.trim()) add(draft); }}
        />
        <button type="button" onClick={() => add(draft)} disabled={!draft.trim()} aria-label="Add skill"><Plus size={14} aria-hidden="true" /></button>
      </span>
    </div>
  );
}

function PersonaPicker({ persona, detected, onChange }: { persona: PersonaId; detected: PersonaId | null; onChange: (id: PersonaId) => void }) {
  return (
    <label className="cr-persona">
      <span className="dc-label">Options tailored for</span>
      <select className="cr-select" value={persona} onChange={(e) => onChange(e.target.value as PersonaId)}>
        {PERSONAS.map((p) => <option key={p.id} value={p.id}>{p.label}{p.id === detected ? " (detected)" : ""}</option>)}
      </select>
    </label>
  );
}

export interface CardEditorProps {
  /** The draft with the person's edits applied, or null until the first build finishes. */
  card: AgentProfileCard | null;
  /** What the sources have revealed so far, shown until the card is written. */
  live: LiveIdentity;
  building: boolean;
  hasSource: boolean;
  persona: PersonaId;
  detectedPersona: PersonaId | null;
  onPersona: (id: PersonaId) => void;
  selections: Selections;
  suggested: Selections;
  onToggleChip: (id: ChipGroupId, label: string) => void;
  onAddChip: (id: ChipGroupId, raw: string) => void;
  location: string;
  locationHint: string;
  onLocation: (value: string) => void;
  /** Name, headline, summary, citation and card style. Links and skills have their own, below. */
  onEdit: (patch: Pick<DraftEdits, "name" | "headline" | "summary" | "citation" | "edition">) => void;
  onRemoveLink: (key: string) => void;
  onAddSkills: (names: string[]) => void;
  onRemoveSkill: (name: string) => void;
  excluded: ReadonlySet<string>;
  onToggleExcluded: (key: string) => void;
  calendly: string;
  googleCalendar: string;
  onCalendly: (value: string) => void;
  onGoogleCalendar: (value: string) => void;
}

function Skeleton() {
  return (
    <div className="cr-block" aria-hidden="true">
      <div className="cr-skel" style={{ height: 14, width: "92%" }} />
      <div className="cr-skel" style={{ height: 14, width: "84%" }} />
      <div className="cr-skel" style={{ height: 14, width: "60%" }} />
    </div>
  );
}

/**
 * Step two: the card as it will be published, filled in as the sources are
 * read. Everything on it is edited where it is drawn.
 */
export function CardEditor(p: CardEditorProps) {
  const { card, live } = p;
  const name = card?.identity.name ?? live.name;
  const headline = card?.identity.headline ?? live.headline;
  const photo = imgProxyUrl(card?.identity.avatar_url || live.avatar);
  const links = card ? Object.entries(card.identity.links).filter(([, v]) => v) : [];
  const waiting = !p.hasSource;

  return (
    <section className="cr-editor" aria-labelledby="cr-editor-h" data-testid="card-editor">
      <div className="cr-step-head">
        <span className="cr-step-n" aria-hidden="true">2</span>
        <div className="cr-head-title">
          <div id="cr-editor-h" className="cr-h">Review your card</div>
          <div className="cr-sub">
            {card ? "This is how it will look. Click any text to change it. Nothing is public until you publish." : "It fills in as your links are read."}
          </div>
        </div>
        <span className="cr-state" data-tone={!p.building && card ? "ok" : undefined}>
          {p.building ? <><span className="cr-spinner" aria-hidden="true" /> Filling in</> : card ? "Draft" : waiting ? "Waiting" : ""}
        </span>
      </div>

      <div className="cr-profile">
        <div className="cr-profile-top">
          {name || headline || card ? (
            <PersonAvatar name={name || "?"} src={photo} size={76} />
          ) : (
            <div className="cr-skel" style={{ width: 76, height: 76, borderRadius: 22, flexShrink: 0 }} aria-hidden="true" />
          )}
          <div className="cr-ident">
            {card ? (
              <>
                <InlineText className="cr-name" label="Name" value={card.identity.name} placeholder="Your name" onChange={(v) => p.onEdit({ name: v })} />
                <InlineText className="cr-headline" label="Headline" value={card.identity.headline} placeholder="What you do, in a few words" onChange={(v) => p.onEdit({ headline: v })} />
                <div className="cr-loc">
                  <MapPin size={14} aria-hidden="true" />
                  <InlineText label="Location" value={p.location} placeholder={p.locationHint ? `e.g. ${p.locationHint}` : "Add your city"} onChange={p.onLocation} />
                </div>
              </>
            ) : name || headline ? (
              <div className="cr-in">
                <div className="cr-name cr-static">{name || "Your name"}</div>
                {headline && <div className="cr-headline cr-static">{headline}</div>}
                {live.location && <div className="cr-loc cr-static"><MapPin size={14} aria-hidden="true" /> {live.location}</div>}
              </div>
            ) : (
              <div style={{ display: "grid", gap: 9 }} aria-hidden="true">
                <div className="cr-skel" style={{ height: 22, width: "55%" }} />
                <div className="cr-skel" style={{ height: 15, width: "75%" }} />
              </div>
            )}
          </div>
        </div>

        <div className="cr-profile-body">
          {links.length > 0 && (
            <div className="cr-links">
              {links.map(([key, url]) => (
                <span key={key} className="dc-chip">
                  <KindIcon kind={detectKind(url)} size={14} />
                  {shortenUrl(url)}
                  <button type="button" aria-label={`Remove ${key} link`} onClick={() => p.onRemoveLink(key)}>
                    <X size={12} aria-hidden="true" />
                  </button>
                </span>
              ))}
            </div>
          )}

          {card ? (
            <InlineArea
              label="Summary" value={card.summary} minRows={3}
              placeholder="Two or three sentences on what you do now and what you're after."
              onChange={(v) => p.onEdit({ summary: v })}
            />
          ) : live.bio ? (
            <div className="cr-static cr-in">{live.bio}</div>
          ) : !waiting ? <Skeleton /> : (
            <div className="cr-empty-note">Paste a link on the left and your card writes itself here.</div>
          )}

          {!card && (live.facts.length > 0 || live.images.length > 0 || live.posts.length > 0) && (
            <div className="cr-block cr-in">
              {live.facts.length > 0 && <div className="dc-chips">{live.facts.map((f) => <span key={f} className="dc-chip dc-chip-plain">{f}</span>)}</div>}
              {live.images.length > 0 && (
                <ul className="cr-gallery is-live">
                  {live.images.map((src) => (
                    <li key={src} className="cr-tile">
                      {/* eslint-disable-next-line @next/next/no-img-element -- remote project covers, proxied */}
                      <img src={imgProxyUrl(src)} alt="" loading="lazy" />
                    </li>
                  ))}
                </ul>
              )}
              {live.posts.map((post) => <div key={post} className="cr-quote">{post}</div>)}
            </div>
          )}

          {!waiting && (
            <>
              <hr className="cr-divider" />
              <div className="cr-block">
                <div className="cr-block-head">
                  <div className="cr-h" style={{ fontSize: 16 }}>About you</div>
                  <PersonaPicker persona={p.persona} detected={p.detectedPersona} onChange={p.onPersona} />
                </div>
                <div className="cr-sub">This is what people and AI agents search on. What we suggested is already chosen.</div>
                {CHIP_GROUPS.map((group) => (
                  <ChipField
                    key={group.id} group={group} options={optionsFor(p.persona, group)}
                    selected={p.selections[group.id]} suggested={p.suggested[group.id]}
                    onToggle={(label) => p.onToggleChip(group.id, label)} onAdd={(raw) => p.onAddChip(group.id, raw)}
                  />
                ))}
              </div>
            </>
          )}

          {card && (
            <>
              <hr className="cr-divider" />
              <div className="cr-block">
                <div className="cr-block-head">
                  <span className="dc-label">Skills</span>
                  <span className="cr-note">{card.skills.length} {card.skills.length === 1 ? "skill" : "skills"}</span>
                </div>
                <SkillsField skills={card.skills} onAdd={p.onAddSkills} onRemove={p.onRemoveSkill} />
              </div>

              {card.github_stats && <GithubBlock stats={card.github_stats} />}
              <WritingBlock samples={card.writing_samples} excluded={p.excluded} onToggle={p.onToggleExcluded} />
              <GalleryBlock items={card.work_gallery ?? []} excluded={p.excluded} onToggle={p.onToggleExcluded} />
              <ProjectsBlock projects={card.projects} excluded={p.excluded} onToggle={p.onToggleExcluded} />

              <hr className="cr-divider" />
              <div className="cr-block">
                <span className="dc-label">Card style</span>
                <EditionPicker
                  value={readEdition(card.identity.edition)}
                  onChange={(next) => p.onEdit({ edition: next })}
                  person={{ name: card.identity.name, headline: card.identity.headline, avatarSrc: imgProxyUrl(card.identity.avatar_url) ?? null }}
                />
              </div>

              <details className="cr-details">
                <summary>More options <span className="cr-note">booking links, how AI agents cite you</span></summary>
                <div className="cr-fields">
                  <label className="cr-field">
                    <span className="dc-label">Calendly link <span className="cr-note">optional</span></span>
                    <input className="cr-input" type="url" inputMode="url" value={p.calendly} placeholder="https://calendly.com/you" onChange={(e) => p.onCalendly(e.target.value)} />
                  </label>
                  <label className="cr-field">
                    <span className="dc-label">Google Calendar link <span className="cr-note">optional</span></span>
                    <input className="cr-input" type="url" inputMode="url" value={p.googleCalendar} placeholder="https://calendar.app.google/…" onChange={(e) => p.onGoogleCalendar(e.target.value)} />
                  </label>
                  <label className="cr-field is-wide">
                    <span className="dc-label">Citation snippet</span>
                    <AutoGrowTextArea value={card.citation_snippet} onChange={(v) => p.onEdit({ citation: v })} minRows={2} className="cr-input" ariaLabel="Citation snippet" />
                    <span className="cr-note">One sentence AI agents quote when they mention you.</span>
                  </label>
                </div>
              </details>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
