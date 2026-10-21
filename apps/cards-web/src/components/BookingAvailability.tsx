"use client";

import { useRef, useState } from "react";

/** Load the live scheduler only after the visitor chooses to open it. */
export function BookingAvailability({ url, name }: { url: string; name: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [opened, setOpened] = useState(false);
  let embed: string | null = null;
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "https:" && ["calendly.com", "www.calendly.com"].includes(parsed.hostname)) {
      parsed.searchParams.set("embed_type", "Inline");
      embed = parsed.toString();
    }
  } catch { /* Direct booking links remain available. */ }
  if (!embed) return <p style={{ fontSize: 12 }}>Open the booking page below to see live availability.</p>;
  return (
    <>
      <button type="button" className="pf-mono" style={{ width: "100%", marginTop: 12, padding: 10, border: "1px solid #93c5fd", borderRadius: 10, fontSize: 12, cursor: "pointer" }} onClick={() => { setOpened(true); dialog.current?.showModal(); }}>View live availability</button>
      <dialog ref={dialog} aria-label={`Book a call with ${name}`} style={{ width: "min(900px, 95vw)", maxWidth: "95vw", padding: 12, borderRadius: 16, border: "1px solid #cbd5e1", color: "#0f172a", background: "#fff" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, padding: 8 }}><strong>Meet {name}</strong><button type="button" onClick={() => dialog.current?.close()}>Close booking</button></div>
        {opened && <iframe title={`Live booking availability for ${name}`} src={embed} style={{ width: "100%", height: "min(700px, 75vh)", border: 0 }} />}
        <a href={url} target="_blank" rel="noreferrer">Open booking page in a new tab ↗</a>
      </dialog>
    </>
  );
}
