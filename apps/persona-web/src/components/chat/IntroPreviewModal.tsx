"use client";

import { useEffect, useRef, useState } from "react";
import { Shield, X } from "lucide-react";
import { Avatar, Button } from "@/components/ui";
import type { PersonaHit } from "./types";

interface IntroPreviewModalProps {
  target: PersonaHit;
  /** The user's own persona name — used to sign the draft as Aria. */
  myName: string;
  onClose: () => void;
  /** Called after the message has been delivered. Receives the new thread id. */
  onSent: (threadId: string) => void;
  /** Posts the message; throws on failure. Returns the created thread id. */
  send: (message: string) => Promise<string>;
}

function firstName(name: string | undefined): string {
  if (!name) return "there";
  return name.trim().split(/\s+/)[0];
}

function buildDraft(target: PersonaHit, myName: string): string {
  const t = firstName(target.name);
  const me = myName || "my person";
  return [
    `Hi ${t} — Aria here, the assistant working with ${me}.`,
    `They've been reading what you've been up to lately and think there's enough overlap to be worth a chat.`,
    "",
    `${me} has some open time this week. Worth a 20-minute call?`,
    "",
    "— Aria",
  ].join("\n");
}

export default function IntroPreviewModal({
  target,
  myName,
  onClose,
  onSent,
  send,
}: IntroPreviewModalProps) {
  const [draft, setDraft] = useState(() => buildDraft(target, myName));
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Close on Escape so the modal feels modeless once you've read it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !sending) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, sending]);

  const handleSend = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    setError(null);
    try {
      const threadId = await send(text);
      onSent(threadId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't send. I'll try again in a minute.");
      setSending(false);
    }
  };

  const focusTextarea = () => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  };

  const headline =
    (target.description || "").split(". ")[0] || "On the Zynd network";

  return (
    <div
      className="intro-modal-scrim"
      onClick={() => !sending && onClose()}
      role="dialog"
      aria-modal="true"
    >
      <div className="intro-modal" onClick={(e) => e.stopPropagation()}>
        <div className="intro-modal-header">
          <Avatar size="sm" name={target.name || "?"} variant="accent" />
          <div className="recipient-info">
            <div className="name">{target.name || "Someone"}</div>
            <div className="title body-s">{headline}</div>
          </div>
          <button
            type="button"
            className="close-btn"
            onClick={onClose}
            disabled={sending}
            aria-label="Close"
          >
            <X size={18} strokeWidth={1.5} />
          </button>
        </div>

        <div className="intro-modal-body">
          <p className="aria-intro body-s">
            Here&apos;s what I&apos;d send to {firstName(target.name)}&apos;s assistant.
            Tweak anything, or send as-is.
          </p>
          {error && (
            <div className="banner banner-danger" role="alert" style={{ marginBottom: 12 }}>
              <span className="banner-msg">⚠ {error}</span>
            </div>
          )}
          <textarea
            ref={textareaRef}
            className="intro-draft"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={sending}
            rows={9}
            aria-label="Intro message draft"
          />
          <div className="trust-line">
            <Shield size={14} strokeWidth={1.5} />
            <span>
              I&apos;ll send this to {firstName(target.name)}&apos;s assistant first.
              {" "}
              {firstName(target.name)} won&apos;t see a raw message from a stranger
              until their assistant says yes.
            </span>
          </div>
        </div>

        <div className="intro-modal-footer">
          <button
            type="button"
            className="text-link"
            onClick={onClose}
            disabled={sending}
          >
            Cancel
          </button>
          <div style={{ display: "flex", gap: 8 }}>
            <Button variant="secondary" onClick={focusTextarea} disabled={sending}>
              Edit more
            </Button>
            <Button onClick={handleSend} disabled={sending || !draft.trim()}>
              {sending ? "Sending…" : "Send it"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
