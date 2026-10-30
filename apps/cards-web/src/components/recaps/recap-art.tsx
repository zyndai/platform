import type { CSSProperties } from "react";
import { profileUrlDisplay } from "@/lib/cards";
import { recapStats, selectedHighlights, type Recap } from "@/lib/recaps";

// Shared by the live preview and PNG renderer. Flex-only CSS also works in next/og.
export function RecapArt({ recap }: { recap: Recap }) {
  const highlights = selectedHighlights(recap);
  const stats = recapStats(highlights);
  const row: CSSProperties = { display: "flex", flexDirection: "row" };
  return (
    <div style={{ display: "flex", flexDirection: "column", width: 1200, height: 630, padding: "48px 56px", background: "#191b33", color: "#faf7ef", fontFamily: "sans-serif", position: "relative", overflow: "hidden" }}>
      <div style={{ position: "absolute", right: -70, top: -180, width: 480, height: 480, borderRadius: 240, background: "#32355d", display: "flex" }} />
      <div style={{ ...row, position: "relative", justifyContent: "space-between", alignItems: "center", fontSize: 20, letterSpacing: 3, color: "#d5ff75" }}>
        <div style={{ display: "flex" }}>ZYND / BUILDER RECAP</div>
        <div style={{ display: "flex", color: "#e4dfff", letterSpacing: 0 }}>{recap.snapshot.label}{recap.snapshot.in_progress ? " · SO FAR" : ""}</div>
      </div>
      <div style={{ display: "flex", fontSize: 62, lineHeight: 1.1, fontWeight: 700, marginTop: 45, maxWidth: 980 }}>{recap.snapshot.name.length > 35 ? `${recap.snapshot.name.slice(0, 32)}…` : recap.snapshot.name}</div>
      <div style={{ display: "flex", fontSize: 29, color: "#c8c3e0", marginTop: 10 }}>Small steps. Real progress.</div>
      <div style={{ ...row, marginTop: 38, gap: 32 }}>
        {stats.map((stat) => (
          <div key={stat.label} style={{ display: "flex", flexDirection: "column", minWidth: 180, flex: 1 }}>
            <div style={{ display: "flex", fontSize: 78, fontWeight: 700, color: "#d5ff75", lineHeight: 1.05 }}>{stat.value}</div>
            <div style={{ display: "flex", marginTop: 8, fontSize: 20, color: "#e4dfff" }}>{stat.label}</div>
          </div>
        ))}
        {!stats.length && <div style={{ display: "flex", fontSize: 32, color: "#c8c3e0" }}>Your next chapter starts here.</div>}
      </div>
      <div style={{ display: "flex", marginTop: 30, fontSize: 21, color: "#e4dfff", height: 52, overflow: "hidden" }}>
        {highlights.filter((h) => h.kind !== "github").slice(0, 2).map((h) => `${h.kind === "shipped" ? "Shipped" : h.kind === "learned" ? "Learned" : "Explored"} ${h.title}`).join("  /  ").slice(0, 120)}
      </div>
      <div style={{ ...row, position: "absolute", bottom: 36, left: 56, right: 56, paddingTop: 20, borderTop: "1px solid #47455f", justifyContent: "space-between", fontSize: 18, color: "#c8c3e0" }}>
        <div style={{ display: "flex" }}>{profileUrlDisplay(recap.handle.slice(0, 40))}</div>
        <div style={{ display: "flex", color: "#d5ff75" }}>Your work deserves to be seen ↗</div>
      </div>
    </div>
  );
}
