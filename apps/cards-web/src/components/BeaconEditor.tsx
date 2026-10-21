"use client";

import { useState } from "react";
import type { Beacon } from "@/lib/cards";
import { ownerRequest } from "@/lib/owner-home";

export function BeaconEditor({ handle, token, initial }: { handle: string; token: string; initial?: Beacon | null }) {
  const [text, setText] = useState(initial?.text ?? "");
  const [beacon, setBeacon] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  async function save(dismiss = false) {
    setBusy(true);
    setNotice("");
    try {
      const result = await ownerRequest<{ beacon: Beacon } | null>(`by-handle/${encodeURIComponent(handle)}/beacon`, token, dismiss ? "DELETE" : "PUT", dismiss ? undefined : { text });
      setBeacon(result?.beacon ?? null);
      if (dismiss) setText("");
      setNotice(dismiss ? "Beacon dismissed" : "Beacon published for seven days");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Could not save your beacon"); }
    finally { setBusy(false); }
  }
  return (
    <section className="pe-card" id="beacon" style={{ padding: 24, marginBottom: 20 }}>
      <h2 style={{ marginTop: 0 }}>Seven-day beacon</h2>
      <p>Tell visitors what you need right now. Publishing or renewing starts a new seven-day window.</p>
      <label htmlFor="beacon-text">Your current request</label>
      <textarea id="beacon-text" className="pe-input" rows={3} maxLength={280} value={text} onChange={e => setText(e.target.value)} placeholder="Seeking early builders to test my new developer tool" />
      {beacon && <p>Last published beacon expires {beacon.expires_at.slice(0, 10)}.</p>}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 12 }}>
        <button type="button" className="pe-btn pe-btn-primary" disabled={busy || !text.trim()} onClick={() => void save()}>{beacon ? "Renew beacon for 7 days" : "Publish beacon for 7 days"}</button>
        {beacon && <button type="button" className="pe-btn pe-btn-secondary" disabled={busy} onClick={() => void save(true)}>Dismiss beacon</button>}
      </div>
      <p role="status">{notice}</p>
    </section>
  );
}
