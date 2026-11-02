"use client";

import { useEffect, useState } from "react";
import type { Beacon } from "@/lib/cards";
import { hostnameOf, kindLabel, safeAskUrl } from "@/lib/asks";

export function BeaconCard({ beacon }: { beacon: Beacon }) {
  const [expired, setExpired] = useState(false);
  useEffect(() => {
    const end = Date.parse(beacon.expires_at);
    const timer = setTimeout(() => setExpired(true), Math.max(0, end - Date.now()));
    return () => clearTimeout(timer);
  }, [beacon.expires_at]);
  if (expired) return null;
  const link = safeAskUrl(beacon.url);
  return (
    <aside aria-label="Current broadcast beacon" className="pf-span-12" style={{ background: "#ecfdf5", border: "1px solid #6ee7b7", borderRadius: 20, padding: "20px 24px" }}>
      <p style={{ fontSize: 11, fontWeight: 800, letterSpacing: ".08em", color: "#047857", margin: "0 0 8px" }}>{beacon.kind ? kindLabel(beacon.kind).toUpperCase() : "LOOKING FOR"} · 7-DAY BEACON</p>
      <p style={{ color: "#064e3b", fontWeight: 600, margin: "0 0 8px", overflowWrap: "anywhere" }}>{beacon.text}</p>
      {link && (
        <p style={{ margin: "0 0 8px" }}>
          <a href={link} target="_blank" rel="noopener noreferrer nofollow ugc" style={{ color: "#047857", fontWeight: 600, overflowWrap: "anywhere" }}>{hostnameOf(link)} ↗</a>
        </p>
      )}
      <small style={{ color: "#047857" }}>Expires <time dateTime={beacon.expires_at}>{beacon.expires_at.slice(0, 10)}</time></small>
    </aside>
  );
}
