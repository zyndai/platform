"use client";

import { useEffect, useState } from "react";

export function VisitorPrivacy({ dark = false }: { dark?: boolean }) {
  const [anonymous, setAnonymous] = useState(true);
  const [available, setAvailable] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const res = await fetch("/api/visitor-privacy", { cache: "no-store" });
        if (!active || res.status === 401) return;
        setSignedIn(true);
        if (!res.ok) { setError("Could not load visitor privacy. Your saved preference still applies."); return; }
        const data = await res.json();
        if (active) { setAnonymous(data.anonymous_mode !== false); setAvailable(true); }
      } catch { if (active) setError("Visitor privacy is unavailable."); }
    })();
    return () => { active = false; };
  }, []);

  async function change(value: boolean) {
    const previous = anonymous;
    setAnonymous(value);
    setBusy(true); setError("");
    try {
      const res = await fetch("/api/visitor-privacy", {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ anonymous_mode: value }),
      });
      if (!res.ok) throw new Error("Could not save visitor privacy. Your previous setting still applies.");
      const data = await res.json();
      setAnonymous(data.anonymous_mode !== false);
      window.dispatchEvent(new Event("zynd:visitor-privacy-changed"));
    } catch (err) { setAnonymous(previous); setError(err instanceof Error ? err.message : "Could not save visitor privacy."); }
    finally { setBusy(false); }
  }
  if (!signedIn) return null;
  return <section aria-label="Visitor privacy" style={{ border: `1px solid ${dark ? "#263146" : "#e2e8f0"}`, borderRadius: 10, padding: 14, marginTop: 16, color: dark ? "#e2e8f0" : "#232329", fontSize: 12 }}>
    <label style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, cursor: "pointer" }}>
      <span>Anonymous browsing</span>
      <input type="checkbox" checked={anonymous} disabled={!available || busy} onChange={e => void change(e.target.checked)} style={{ accentColor: "#7B72E9" }} />
    </label>
    <p style={{ fontSize: 11, margin: "8px 0 0", lineHeight: 1.6, color: dark ? "#94a3b8" : "#64748b" }}>
      {busy ? "Saving your browsing preference…" : !available ? "Your saved preference still applies; it could not be loaded right now." : anonymous ? "On: profile owners won't see your name. Turn off only if you agree to share your name when visiting profiles." : "Off: you agree to share your name with profile owners you visit. Turn on to hide your name, including earlier visits."}
    </p>
    {error && <p role="alert" style={{ color: dark ? "#fda4af" : "#9f1239", fontSize: 11 }}>{error}</p>}
  </section>;
}
