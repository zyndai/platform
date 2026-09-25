"use client";

import { groupMemoryFacts, type MemoryFact } from "@/lib/memory-facts";

export function MemoryTilePreview({
  firstName,
  facts,
  selectedKeys,
  onToggle,
}: {
  firstName: string;
  facts: MemoryFact[];
  selectedKeys?: Set<string>;
  onToggle?: (key: string) => void;
}) {
  const groups = groupMemoryFacts(facts);
  const total = groups.reduce((n, group) => n + group.items.length, 0);
  const name = firstName.trim() || "You";

  return (
    <div
      style={{
        background: "#0f172a",
        borderRadius: 20,
        padding: 16,
        color: "#fff",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        minWidth: 0,
        width: "100%",
      }}
    >
      <div
        style={{
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: "0.65rem",
          fontWeight: 700,
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 12,
        }}
      >
        <span>● ZYND MEMORY</span>
        <span style={{ color: "#64748b" }}>PREVIEW</span>
      </div>
      <div style={{ fontSize: "1.1rem", fontWeight: 800, marginBottom: 2 }}>
        What {name}&apos;s working on
      </div>
      <div style={{ fontSize: "0.75rem", color: "#94a3b8", marginBottom: 12 }}>
        {onToggle ? "Tap a chip to keep or drop it before approving." : "Synced from coding agents"}
      </div>
      {total === 0 ? (
        <div style={{ fontSize: "0.8rem", color: "#94a3b8", padding: "12px 0" }}>
          No public key points in that memory yet.
        </div>
      ) : (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 10,
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            fontSize: "0.7rem",
          }}
        >
          {groups.slice(0, 3).map((group) => (
            <div key={group.key}>
              <span style={{ color: "#fbbf24" }}>▼</span>{" "}
              <span style={{ textTransform: "uppercase", letterSpacing: "0.05em" }}>{group.label}</span>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
                {group.items.slice(0, 3).map((item) => {
                  const key = `${group.key}|${item.object.toLowerCase()}`;
                  const on = !selectedKeys || selectedKeys.has(key);
                  return (
                    <button
                      key={key}
                      type="button"
                      onClick={onToggle ? () => onToggle(key) : undefined}
                      disabled={!onToggle}
                      style={{
                        background: on ? "rgba(255,255,255,0.1)" : "rgba(255,255,255,0.03)",
                        color: on ? "#fff" : "#64748b",
                        textDecoration: on ? "none" : "line-through",
                        border: "none",
                        borderRadius: 6,
                        padding: "2px 6px",
                        fontSize: "0.6rem",
                        cursor: onToggle ? "pointer" : "default",
                      }}
                    >
                      {item.text}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
      <div
        style={{
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          display: "flex",
          justifyContent: "space-between",
          marginTop: 12,
          paddingTop: 12,
          borderTop: "1px solid rgba(255,255,255,0.08)",
          fontSize: "0.6rem",
          color: "#64748b",
        }}
      >
        <span>{total} KEY POINTS</span>
        <span>ZYND</span>
      </div>
    </div>
  );
}
