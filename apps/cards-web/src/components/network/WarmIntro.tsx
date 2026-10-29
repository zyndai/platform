"use client";

import { useState } from "react";
import Link from "next/link";
import { Sparkles } from "lucide-react";
import { cardsNetworkRequest, type CardConnection } from "@/lib/cards-network";

interface Draft {
  target_handle: string;
  name: string;
  message: string;
  reasons: string[];
}

const DRAFT_TIMEOUT_MS = 30_000;

/** Generating a draft is read-only. Sending is the owner's explicit first approval. */
export function WarmIntro({ handle, name, token }: { handle: string; name: string; token: string }) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [message, setMessage] = useState("");
  const [phase, setPhase] = useState<"drafting" | "sending" | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState<CardConnection | null>(null);
  const busy = phase !== null;

  async function prepare() {
    setEditorOpen(true);
    setPhase("drafting");
    setError("");
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), DRAFT_TIMEOUT_MS);
    try {
      const result = await cardsNetworkRequest<Draft>("/warm-intros/draft", token, "POST", { target_handle: handle }, controller.signal);
      setDraft(result);
      setMessage(result.message);
    } catch (failure) {
      setError(controller.signal.aborted ? "Drafting took too long. Please try again. No introduction was sent."
        : failure instanceof Error ? failure.message : "Could not draft this introduction. Please try again.");
    } finally { window.clearTimeout(timeout); setPhase(null); }
  }

  async function send() {
    if (!message.trim()) return;
    setPhase("sending");
    setError("");
    try {
      const result = await cardsNetworkRequest<{ connection: CardConnection; existing: boolean }>("/warm-intros", token, "POST", {
        target_handle: handle, message: message.trim(),
      });
      if (!["pending", "accepted"].includes(result.connection.status)) {
        throw new Error("An introduction to this person is no longer available.");
      }
      setConnection(result.connection);
      setDraft(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not send. Your draft is saved here; try again.");
    } finally { setPhase(null); }
  }

  return <div className="oh-warm-intro">
    {connection ? <div role="status">
      <p>{connection.status === "accepted" ? "You’re connected. Your conversation is ready."
        : connection.incoming ? `${name} already sent you a request. Review it in your inbox.`
          : "Intro request sent. Your conversation opens when they accept."}</p>
      <Link className="oh-text-link" href={`/network?c=${encodeURIComponent(connection.id)}`}>
        {connection.status === "accepted" ? "Open conversation →" : "View request →"}
      </Link>
    </div> : editorOpen ? <section aria-label={`Intro draft for ${name}`} className="oh-intro-draft" aria-busy={phase === "drafting"}>
      <h3><Sparkles size={15} aria-hidden="true" /> Your intro, drafted by DearAgent</h3>
      {phase === "drafting" ? <p role="status">Checking your profiles and drafting an introduction… Nothing has been sent.</p> : draft ? <>
      <ul>{draft.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
      <label>Introduction to {name}
        <textarea value={message} onChange={event => setMessage(event.target.value)} maxLength={2000} rows={6} disabled={busy} />
      </label>
      <p>Edit before sending. They’ll receive a connection request and can accept or decline.</p>
      <div className="oh-intro-actions">
        <button className="oh-button" type="button" disabled={busy || !message.trim()} onClick={() => void send()}>
          {busy ? "Sending…" : "Send intro request"}
        </button>
      </div>
      </> : <button className="oh-button oh-outline" type="button" onClick={() => void prepare()}>Try drafting again</button>}
      {error && <p className="oh-intro-error" role="alert">{error}</p>}
      <button className="oh-text-link" type="button" disabled={busy} onClick={() => { setEditorOpen(false); setDraft(null); setError(""); }}>Cancel</button>
    </section> : <button className="oh-button oh-outline" type="button" disabled={busy} onClick={() => void prepare()} aria-label={`Draft an intro to ${name}`}>
      <Sparkles size={14} aria-hidden="true" /> {busy ? "Drafting…" : "Draft an intro"}
    </button>}
  </div>;
}
