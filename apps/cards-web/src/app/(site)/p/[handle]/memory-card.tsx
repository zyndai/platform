"use client";

import { useState } from "react";

export interface MemoryGroupItem {
  text: string;
  inferred: boolean;
  confidence: number;
  approved_at: string;
}

export interface MemoryGroup {
  key: string;
  label: string;
  icon: string;
  items: MemoryGroupItem[];
}

interface MemoryCardProps {
  firstName: string;
  groups: MemoryGroup[];
  total: number;
}

/** ZYND memory tile: shows the top facts collapsed with a "See all" expander
 *  so long lists never hide content behind a scroll without a cue. */
export function MemoryCard({ firstName, groups, total }: MemoryCardProps) {
  const [expanded, setExpanded] = useState(false);
  const visibleGroups = expanded ? groups : groups.slice(0, 3);
  const hiddenCount = total - visibleGroups.reduce(
    (n, g) => n + (expanded ? g.items.length : Math.min(g.items.length, 3)),
    0,
  );

  return (
    <div
      className="pf-social-card"
      style={{ background: "#0f172a", borderRadius: 20, padding: 16, color: "#fff", overflow: "hidden", display: "flex", flexDirection: "column" }}
    >
      <div className="pf-mono flex justify-between items-start mb-3" style={{ fontSize: "0.65rem", fontWeight: 700 }}>
        <span>● MEMORY</span>
        <span style={{ color: "#64748b" }}>LIVE</span>
      </div>
      <div style={{ fontSize: "1.1rem", fontWeight: 800, marginBottom: 2 }}>What {firstName}&apos;s working on</div>
      <div style={{ fontSize: "0.75rem", fontWeight: 400, color: "#94a3b8", marginBottom: 12 }}>Synced from coding agents</div>
      <div className="pf-mono flex-1" style={{ display: "flex", flexDirection: "column", gap: 10, fontSize: "0.7rem", overflow: "hidden" }}>
        {visibleGroups.map((g) => (
          <div key={g.key}>
            <span style={{ color: "#fbbf24" }}>▼</span>{" "}
            <span style={{ textTransform: "uppercase", letterSpacing: "0.05em" }}>{g.label}</span><br />
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
              {(expanded ? g.items : g.items.slice(0, 3)).map((item) => (
                <span key={item.text} style={{ background: "rgba(255,255,255,0.1)", borderRadius: 6, padding: "2px 6px", fontSize: "0.6rem" }}>
                  {item.text}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
      {hiddenCount > 0 && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="pf-mono"
          style={{
            marginTop: 10, alignSelf: "flex-start", background: "rgba(255,255,255,0.08)",
            border: "1px solid rgba(255,255,255,0.12)", color: "#e2e8f0", borderRadius: 99,
            padding: "4px 12px", fontSize: "0.62rem", fontWeight: 700, cursor: "pointer",
          }}
        >
          {expanded ? "Show less" : `See all (${hiddenCount} more)`}
        </button>
      )}
      <div className="pf-mono flex justify-between mt-auto pt-3" style={{ borderTop: "1px solid rgba(255,255,255,0.08)", fontSize: "0.6rem", color: "#64748b" }}>
        <span>{total} MEMORY FACTS</span>
        <span>ZYND</span>
      </div>
    </div>
  );
}