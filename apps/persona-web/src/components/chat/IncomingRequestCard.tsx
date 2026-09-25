"use client";

/**
 * Inline reply composer for an inbound A2A request, rendered in the
 * home chat thread. Shown when ChatProvider's dm_messages realtime
 * subscription detects a peer agent reaching out to us on the agent
 * channel.
 *
 * On submit we POST to /api/persona/{user_id}/agent-send with the
 * dm_thread id — same endpoint the Threads page uses, so the wire
 * format and acceptance semantics are identical.
 */

import { useEffect, useRef, useState } from "react";
import { ExternalLink, MailOpen } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui";
import type { IncomingRequest } from "./types";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface IncomingRequestCardProps {
  request: IncomingRequest;
  userId: string;
  /** Called once a reply has been sent successfully so the card can
   *  flip into a "replied" state in the parent's message list. */
  onReplied: () => void;
}

export default function IncomingRequestCard({
  request,
  userId,
  onReplied,
}: IncomingRequestCardProps) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-grow up to 6 rows — matches the chat composer behavior so the
  // surface feels consistent.
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const lineHeight = 22;
    const max = lineHeight * 6 + 8;
    ta.style.height = Math.min(ta.scrollHeight, max) + "px";
    ta.style.overflowY = ta.scrollHeight > max ? "auto" : "hidden";
  }, [draft]);

  if (request.replied) {
    return (
      <div className="incoming-card incoming-card-replied">
        <div className="incoming-card-head">
          <MailOpen size={14} strokeWidth={1.5} />
          <span>
            Reply sent to <strong>{request.peerLabel}</strong>
          </span>
        </div>
      </div>
    );
  }

  const handleSend = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    setError(null);
    try {
      const res = await fetch(`${API}/api/persona/${userId}/agent-send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: request.threadId, content: text }),
      });
      if (!res.ok) {
        throw new Error((await res.text()) || "send failed");
      }
      const data = await res.json().catch(() => null);
      const delivery = data?.delivery;
      if (delivery && delivery.delivered === false) {
        const reason = delivery.error_reason || delivery.error || "delivery_failed";
        if (reason === "awaiting_acceptance") {
          throw new Error(
            "They haven't accepted the connection yet — try again once they do.",
          );
        }
        throw new Error(`The peer rejected the reply (${reason}).`);
      }
      onReplied();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't send.");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="incoming-card">
      <div className="incoming-card-head">
        <MailOpen size={14} strokeWidth={1.5} />
        <span>
          Incoming from <strong>{request.peerLabel}</strong>{" "}
          <span className="incoming-card-channel">· agent channel</span>
        </span>
      </div>

      <div className="incoming-card-body">{request.body}</div>

      <textarea
        ref={textareaRef}
        rows={2}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            void handleSend();
          }
        }}
        placeholder={`Reply to ${request.peerLabel}…`}
        disabled={sending}
        className="incoming-card-composer"
        aria-label={`Reply to ${request.peerLabel}`}
      />

      {error && <div className="incoming-card-error body-s">{error}</div>}

      <div className="incoming-card-actions">
        <Link
          href={`/dashboard/messages?thread=${request.threadId}`}
          className="incoming-card-link"
          aria-label="Open thread"
        >
          Open thread
          <ExternalLink size={12} strokeWidth={1.5} />
        </Link>
        <Button
          size="sm"
          disabled={sending || !draft.trim()}
          onClick={handleSend}
        >
          {sending ? "Sending…" : "Send reply"}
        </Button>
      </div>
    </div>
  );
}
