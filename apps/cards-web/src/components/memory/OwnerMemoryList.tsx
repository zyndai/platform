"use client";

import { useState } from "react";
import { ownerFactCount, type OwnerFactGroup } from "@/lib/memory-facts";

const COLLAPSED_LIMIT = 6;

/** The owner's public memory facts grouped by card section. Each fact shows where it came
 *  from and, when known, the sentence behind it ("Because"), so "Expert in X" is never
 *  unexplained. Nothing is silently capped: collapsed shows the first few, "Show all"
 *  shows every one, and the count the editor prints is the sum of these groups. */
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
    <div data-testid="owner-memory-list" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {visible.map((g) => (
        <div key={g.key} data-group={g.key}>
          <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase", color: "#6b6b66", marginBottom: 6 }}>
            {g.label}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {g.items.map((item) => (
              <div key={item.key} className="pe-mem" data-fact={item.text}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ color: "#1d1d1b", fontWeight: 600 }}>{item.text}</span>
                  {item.provenanceLabel && (
                    <span data-provenance={item.provenance} style={{ fontSize: 11, color: "#6b6b66", border: "1px solid #e1e0d8", borderRadius: 99, padding: "1px 8px" }}>
                      {item.provenanceLabel}
                    </span>
                  )}
                </div>
                {item.evidence && (
                  <div style={{ fontSize: 12, color: "#6b6b66", marginTop: 4 }}>
                    Because: &ldquo;{item.evidence}&rdquo;
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
      {total > shown && (
        <button type="button" className="pe-ghost" style={{ alignSelf: "flex-start" }} onClick={() => setExpanded(true)}>
          Show all {total}
        </button>
      )}
      {expanded && total > COLLAPSED_LIMIT && (
        <button type="button" className="pe-ghost" style={{ alignSelf: "flex-start" }} onClick={() => setExpanded(false)}>
          Show fewer
        </button>
      )}
    </div>
  );
}
