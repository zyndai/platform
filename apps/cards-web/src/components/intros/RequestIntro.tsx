"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { createClient } from "@/lib/supabase/client";
import { ownerRequest } from "@/lib/owner-home";
import type { Intro } from "@/lib/intros";
import "./intros.css";

export function RequestIntro({ handle }: { handle: string }) {
  const { authenticated } = useAuth();
  const [available, setAvailable] = useState(false);
  const [open, setOpen] = useState(false);
  const [why, setWhy] = useState("");
  const [meeting, setMeeting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Intro | null>(null);
  const submission = useRef<{ payload: string; key: string } | null>(null);
  useEffect(() => {
    let cancelled = false;
    const api = (process.env.NEXT_PUBLIC_API_URL || "https://api.zynd.ai").replace(/\/$/, "");
    fetch(`${api}/cards/by-handle/${encodeURIComponent(handle)}/intro-eligibility`, { cache: "no-store" })
      .then(r => r.ok ? r.json() : { available: false })
      .then(data => { if (!cancelled) setAvailable(data.available === true); })
      .catch(() => { if (!cancelled) setAvailable(false); });
    return () => { cancelled = true; };
  }, [handle]);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const { data: { session } } = await createClient().auth.getSession();
      if (!session) throw new Error("Sign in before requesting an intro.");
      const body = { why: why.trim(), asks: meeting ? ["message", "meeting"] : ["message"] };
      const payload = JSON.stringify(body);
      if (!submission.current || submission.current.payload !== payload) {
        submission.current = { payload, key: crypto.randomUUID() };
      }
      setResult(await ownerRequest<Intro>(`by-handle/${encodeURIComponent(handle)}/intro`, session.access_token,
        "POST", { ...body, idempotency_key: submission.current.key }));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not send. Please retry.");
    } finally { setBusy(false); }
  }

  if (!available) return null;
  if (result) return <aside aria-live="polite" style={{ padding: 20 }}>
    <h2>Your intro request is {result.status}</h2>
    <p>The owner decides whether to connect. No meeting has been booked.</p>
    <Link href="/intros?outgoing=true">View your sent requests →</Link>
  </aside>;
  return <section className="intro-request" style={{ marginBottom: 20 }}>
    <button type="button" className="oh-button" onClick={() => setOpen(!open)} aria-expanded={open}>Request intro</button>
    {open && (!authenticated ? <p><Link href={`/auth?next=${encodeURIComponent(`/p/${handle}`)}`}>Sign in to request an intro</Link></p> :
      <form onSubmit={send}>
        <p>Your verified account identifies you. Explain why you want to connect.</p>
        <label>Reason for connecting<textarea required minLength={10} maxLength={2000} value={why}
          onChange={e => setWhy(e.target.value)} disabled={busy} style={{ display: "block", width: "100%", minHeight: 100 }} /></label>
        <label><input type="checkbox" checked={meeting} disabled={busy} onChange={e => setMeeting(e.target.checked)} /> I would also like to arrange a call</label>
        <p>You both need an active Persona and linked Zynd memory account.</p>
        <p role="alert">{error}</p>
        <button disabled={busy || why.trim().length < 10} type="submit">{busy ? "Sending…" : "Send intro request"}</button>
      </form>)}
  </section>;
}
