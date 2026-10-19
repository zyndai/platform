"use client";

import { useState } from "react";
import { ownerFactCount, type OwnerFactGroup } from "@/lib/memory-facts";

const COLLAPSED_LIMIT = 6;

/** The owner's public memory facts grouped by card section. Each fact shows where it came
 *  from and, when known, the sentence behind it ("Because"), so "Expert in X" is never
 *  unexplained. Nothing is silently capped: collapsed shows the first few, "Show all"
 *  shows every one, and the count the editor prints is the sum of these groups.
 *  Styled by the card editor's edit.css (pe-* classes). */
export function OwnerMemoryList({ groups }: { groups: OwnerFactGroup[] }) {
  const [expanded, setExpanded] = useState(false);
  const total = ownerFactCount(groups);
  const limit = expanded ? Infinity : COLLAPSED_LIMIT;

  // Take the first `limit` facts across groups in order, without mutating during render.
  const visible = groups
    .map((g, i) => {
      const before = groups.slice(0, i).reduce((n, prev) => n + prev.items.length, 0);
      return { ...g, items: g.items.slice(0, Math.max(0, limit - before)) };
    })
    .filter((g) => g.items.length > 0);
  const shown = ownerFactCount(visible);

  return (
    <div data-testid="owner-memory-list" className="pe-mem-groups">
      {visible.map((g) => (
        <div key={g.key} data-group={g.key}>
          <div className="pe-mem-group-label">{g.label}</div>
          <div className="pe-mem-items">
            {g.items.map((item) => (
              <div key={item.key} className="pe-mem" data-fact={item.text}>
                <div className="pe-mem-line">
                  <span className="pe-mem-text">{item.text}</span>
                  {item.provenanceLabel && (
                    <span data-provenance={item.provenance} className="pe-src">
                      {item.provenanceLabel}
                    </span>
                  )}
                </div>
                {item.evidence && (
                  <div className="pe-mem-why">
                    Because: &ldquo;{item.evidence}&rdquo;
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
      {total > shown && (
        <button type="button" className="pe-btn-link" style={{ alignSelf: "flex-start" }} onClick={() => setExpanded(true)}>
          Show all {total}
        </button>
      )}
      {expanded && total > COLLAPSED_LIMIT && (
        <button type="button" className="pe-btn-link" style={{ alignSelf: "flex-start" }} onClick={() => setExpanded(false)}>
          Show fewer
        </button>
      )}
    </div>
  );
}
