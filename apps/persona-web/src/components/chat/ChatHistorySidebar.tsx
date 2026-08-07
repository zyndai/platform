"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { getSupabase } from "@/lib/supabase";
import { useChat, type ChatSession } from "@/contexts/ChatContext";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diffMs = Date.now() - then;
  const min = Math.floor(diffMs / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day}d ago`;
  return new Date(iso).toLocaleDateString();
}

/**
 * Collapsible session-history drawer for the Persona · Home chat. Toggled
 * from AppTopBar's history button. Sessions are derived entirely from
 * chat_messages via /api/chat/conversations — clicking "New chat" doesn't
 * need to explicitly "move" the old thread anywhere, it's already the same
 * data this list reads, just under its own conversation_id.
 */
export default function ChatHistorySidebar() {
  const { conversationId, historyOpen, toggleHistory, loadConversation } = useChat();
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!historyOpen) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const sb = getSupabase();
        const { data: { session } } = await sb.auth.getSession();
        if (!session?.access_token) return;
        const res = await fetch(`${API}/api/chat/conversations`, {
          headers: { Authorization: `Bearer ${session.access_token}` },
        });
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) setSessions(data.conversations || []);
      } catch {
        /* best-effort */
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [historyOpen]);

  // Close on Escape.
  useEffect(() => {
    if (!historyOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") toggleHistory();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [historyOpen, toggleHistory]);

  if (!historyOpen) return null;

  return (
    <>
      <div className="chat-history-scrim" onClick={toggleHistory} />
      <aside className="chat-history-drawer" role="dialog" aria-label="Chat history">
        <div className="chat-history-head">
          <span className="chat-history-title">Chat history</span>
          <button
            type="button"
            className="chat-history-close"
            onClick={toggleHistory}
            aria-label="Close chat history"
          >
            <X size={16} strokeWidth={1.7} />
          </button>
        </div>

        {loading ? (
          <div className="chat-history-empty">Loading…</div>
        ) : sessions.length === 0 ? (
          <div className="chat-history-empty">No past sessions yet.</div>
        ) : (
          <div className="chat-history-list">
            {sessions.map((s) => (
              <button
                key={s.conversation_id}
                type="button"
                className={`chat-history-item ${s.conversation_id === conversationId ? "active" : ""}`}
                onClick={() => loadConversation(s.conversation_id)}
              >
                <span className="chat-history-item-preview">{s.preview}</span>
                <span className="chat-history-item-time">{relativeTime(s.updated_at)}</span>
              </button>
            ))}
          </div>
        )}
      </aside>
    </>
  );
}
