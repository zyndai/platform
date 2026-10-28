"use client";

import { useId, useState } from "react";
import { Plus, Sparkles, X } from "lucide-react";

import { hasLabel, type ChipGroup } from "./chips";

/** Presets offered one tap away beside the chosen chips; the rest sit behind "Show all". */
const QUICK_OPTIONS = 4;

/**
 * One of the card's answer lines. What the AI suggested is already chosen and
 * marked; a tap removes a chip, a tap on a dashed one adds it, and anything can be typed.
 */
export function ChipField({ group, options, selected, suggested, onToggle, onAdd }: {
  group: ChipGroup;
  /** The persona's preset labels for this group. */
  options: string[];
  selected: string[];
  suggested: string[];
  onToggle: (label: string) => void;
  onAdd: (raw: string) => void;
}) {
  const tipId = useId();
  const [draft, setDraft] = useState("");
  const [showAll, setShowAll] = useState(false);

  const free = options.filter((o) => !hasLabel(selected, o));
  const quick = free.slice(0, QUICK_OPTIONS);
  const rest = free.slice(QUICK_OPTIONS);
  const commit = () => { if (draft.trim()) { onAdd(draft); setDraft(""); } };

  return (
    <div className="cr-group" role="group" aria-label={group.label}>
      <div className="cr-group-head">
        <span className="dc-label">{group.label}</span>
        <span className="cr-tip" id={tipId}>{group.tip}</span>
      </div>
      <div className="cr-chips">
        {selected.map((label) => (
          <span key={label} className="cr-pick" data-suggested={hasLabel(suggested, label) || undefined}>
            {hasLabel(suggested, label) && <Sparkles size={12} aria-label="Suggested from your profiles" role="img" />}
            {label}
            <button type="button" aria-label={`Remove ${label}`} onClick={() => onToggle(label)}><X size={13} aria-hidden="true" /></button>
          </span>
        ))}
        {(showAll ? free : quick).map((label) => (
          <button key={label} type="button" className="cr-suggest" aria-label={`Add ${label}`} onClick={() => onToggle(label)}>
            <Plus size={12} aria-hidden="true" /> {label}
          </button>
        ))}
        <span className="cr-add">
          <input
            value={draft} placeholder="Add your own" aria-label={`Add your own: ${group.label}`} aria-describedby={tipId}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }}
          />
          <button type="button" onClick={commit} disabled={!draft.trim()} aria-label={`Add to ${group.label}`}><Plus size={14} aria-hidden="true" /></button>
        </span>
      </div>
      {rest.length > 0 && (
        <button type="button" className="cr-more" aria-expanded={showAll} onClick={() => setShowAll((v) => !v)}>
          {showAll ? "Show fewer" : `Show all ${free.length} options`}
        </button>
      )}
    </div>
  );
}
