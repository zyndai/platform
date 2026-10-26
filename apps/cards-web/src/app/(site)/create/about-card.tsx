"use client";

import { useState } from "react";
import { Plus, Sparkles } from "lucide-react";

import { CHIP_GROUPS, hasLabel, sameLabel, type ChipGroup, type ChipGroupId, type Selections } from "./chips";

/** The order a group's chips are drawn in: the AI's picks first, then what the person typed, then the rest. */
function chipOrder(group: ChipGroup, suggested: string[], selected: string[]): string[] {
  const out: string[] = [];
  const push = (label: string) => { if (!hasLabel(out, label)) out.push(label); };
  suggested.forEach((s) => push(group.options.find((o) => sameLabel(o, s)) ?? s));
  selected.filter((s) => !hasLabel(group.options, s)).forEach(push);
  group.options.forEach(push);
  return out;
}

function ChipGroupField({ group, selected, suggested, onToggle, onAdd }: {
  group: ChipGroup;
  selected: string[];
  suggested: string[];
  onToggle: (label: string) => void;
  onAdd: (raw: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const commit = () => { if (draft.trim()) { onAdd(draft); setDraft(""); } };

  return (
    <div className="cr-group" role="group" aria-label={group.label}>
      <div className="cr-group-q">
        {group.label}
        {selected.length > 0 && <small>{selected.length} picked</small>}
      </div>
      <div className="cr-chips">
        {chipOrder(group, suggested, selected).map((label) => (
          <button
            key={label} type="button" className="dc-toggle"
            aria-pressed={hasLabel(selected, label)}
            title={hasLabel(suggested, label) ? "Suggested from your profiles" : undefined}
            onClick={() => onToggle(label)}
          >
            {hasLabel(suggested, label) && <Sparkles size={12} aria-hidden="true" />}
            {label}
          </button>
        ))}
        <span className="cr-add">
          <input
            value={draft} placeholder="Add your own" aria-label={`Add your own: ${group.label}`}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }}
          />
          <button type="button" onClick={commit} disabled={!draft.trim()} aria-label="Add"><Plus size={14} aria-hidden="true" /></button>
        </span>
      </div>
    </div>
  );
}

/** What the person is about. The AI fills it in from the profiles; everything stays one tap to change. */
export function AboutCard({ selections, suggested, building, location, locationHint, calendly, googleCalendar, onToggle, onAdd, onLocation, onCalendly, onGoogleCalendar }: {
  selections: Selections;
  suggested: Selections;
  building: boolean;
  location: string;
  locationHint: string;
  calendly: string;
  googleCalendar: string;
  onToggle: (id: ChipGroupId, label: string) => void;
  onAdd: (id: ChipGroupId, raw: string) => void;
  onLocation: (value: string) => void;
  onCalendly: (value: string) => void;
  onGoogleCalendar: (value: string) => void;
}) {
  const anySuggested = CHIP_GROUPS.some((g) => suggested[g.id].length > 0);

  return (
    <section className="cr-card" aria-labelledby="cr-about-h">
      <div className="cr-head">
        <div className="cr-head-title">
          <div id="cr-about-h" className="cr-h">About you</div>
          <div className="cr-sub">This is what people and AI agents search on. Tap to pick; add your own anywhere.</div>
        </div>
        {anySuggested ? (
          <span className="cr-legend"><Sparkles size={13} aria-hidden="true" /> Suggested from your profiles</span>
        ) : building ? (
          <span className="cr-legend"><span className="cr-spinner" aria-hidden="true" /> Suggestions appear once your profiles are read</span>
        ) : null}
      </div>

      {CHIP_GROUPS.map((group) => (
        <ChipGroupField
          key={group.id} group={group}
          selected={selections[group.id]} suggested={suggested[group.id]}
          onToggle={(label) => onToggle(group.id, label)} onAdd={(raw) => onAdd(group.id, raw)}
        />
      ))}

      <hr className="cr-divider" />

      <div className="cr-fields">
        <label className="cr-field is-wide">
          <span className="dc-label">Where are you based?</span>
          <input
            className="cr-input" value={location} autoComplete="off"
            placeholder={locationHint ? `e.g. ${locationHint}` : "e.g. San Francisco, CA"}
            onChange={(e) => onLocation(e.target.value)}
          />
        </label>
        <label className="cr-field">
          <span className="dc-label">Calendly link <span className="cr-note">optional</span></span>
          <input className="cr-input" type="url" inputMode="url" value={calendly} placeholder="https://calendly.com/you" onChange={(e) => onCalendly(e.target.value)} />
        </label>
        <label className="cr-field">
          <span className="dc-label">Google Calendar link <span className="cr-note">optional</span></span>
          <input className="cr-input" type="url" inputMode="url" value={googleCalendar} placeholder="https://calendar.app.google/…" onChange={(e) => onGoogleCalendar(e.target.value)} />
        </label>
      </div>
    </section>
  );
}
