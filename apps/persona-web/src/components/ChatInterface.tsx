"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getSupabase } from "@/lib/supabase";

interface ToolCallState {
  id: string;
  name: string;
  argsText: string;                       // accumulated JSON fragment
  arguments?: Record<string, unknown>;    // parsed args when tool_call_end arrives
  result?: unknown;                       // filled in on tool_result
  status: "running" | "done" | "error";
}

interface Message {
  role: "user" | "assistant";
  content: string;
  thinking?: string;                      // reasoning stream (if provider exposes it)
  toolCalls?: ToolCallState[];            // live tool-call progress during streaming
  actions?: { tool: string; args?: unknown; result: unknown }[];
  timestamp: Date;
  streaming?: boolean;                    // true while SSE is open
  error?: string;
}

// ── Hand-off helpers ─────────────────────────────────────────────────
//
// The orchestrator returns `actions_taken` describing every tool call it
// made during a turn. We scan it for two things:
//
//   1. Network discovery results (search_zynd_personas / get_persona_profile)
//      → render the hits as inline persona cards with [Open Conversation] buttons.
//
//   2. AI-initiated thread actions (request_connection / message_zynd_agent)
//      → render a hand-off CTA so the user can take over the conversation.
//
// Both come from the same `actions` array; we pull whichever is present.

interface PersonaHit {
  agent_id: string;
  name?: string;
  description?: string;
}

interface ThreadHandoff {
  thread_id: string;
  partner_name?: string;
  partner_agent_id?: string;
  source_tool: string;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function extractPersonaHits(actions: Message["actions"]): PersonaHit[] {
  if (!actions) return [];
  const hits: PersonaHit[] = [];
  const seen = new Set<string>();
  for (const a of actions) {
    if (a.tool !== "search_zynd_personas") continue;
    const r = a.result;
    if (!isPlainObject(r)) continue;
    const list = r.results;
    if (!Array.isArray(list)) continue;
    for (const item of list) {
      if (!isPlainObject(item)) continue;
      const id = typeof item.agent_id === "string" ? item.agent_id : "";
      if (!id || seen.has(id)) continue;
      seen.add(id);
      hits.push({
        agent_id: id,
        name: typeof item.name === "string" ? item.name : undefined,
        description: typeof item.description === "string" ? item.description : undefined,
      });
    }
  }
  return hits;
}

// Tool calls that produce a thread the user might want to jump into
const HANDOFF_TOOLS = new Set([
  "request_connection",
  "message_zynd_agent",
  "propose_meeting",
]);

function extractHandoffs(actions: Message["actions"]): ThreadHandoff[] {
  if (!actions) return [];
  const handoffs: ThreadHandoff[] = [];
  const seen = new Set<string>();
  for (const a of actions) {
    if (!HANDOFF_TOOLS.has(a.tool)) continue;
    const r = a.result;
    if (!isPlainObject(r)) continue;
    const tid = typeof r.thread_id === "string" ? r.thread_id : "";
    if (!tid || seen.has(tid)) continue;
    seen.add(tid);
    handoffs.push({
      thread_id: tid,
      partner_name: typeof r.partner_name === "string" ? r.partner_name : undefined,
      partner_agent_id: typeof r.partner_agent_id === "string" ? r.partner_agent_id : undefined,
      source_tool: a.tool,
    });
  }
  return handoffs;
}

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function ChatInterface() {
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [busyHit, setBusyHit] = useState<string | null>(null);
  // Per-message index of whether the thinking block is expanded.
  // Collapsed by default (like ChatGPT / Claude / Gemini).
  const [expandedThinking, setExpandedThinking] = useState<Set<number>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);

  const toggleThinking = (idx: number) => {
    setExpandedThinking((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  // Return the last non-empty line of a thinking string. Used as the
  // one-line preview while the thinking block is collapsed — ticker-style
  // so the user sees the latest reasoning step as it arrives.
  const lastThinkingLine = (text?: string): string => {
    if (!text) return "";
    const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
    return lines.length > 0 ? lines[lines.length - 1] : "";
  };

  // Resolve the current Supabase user once so the hand-off / open-conversation
  // helpers can talk to /api/persona/{user_id}/threads.
  useEffect(() => {
    getSupabase()
      .auth.getSession()
      .then(({ data }) => setUserId(data.session?.user?.id ?? null));
  }, []);

  // Open a thread in the Messages tab WITHOUT changing its mode.
  // Used for meeting hand-offs: meetings live happily in agent-mode threads,
  // we just want to jump there without reframing the conversation.
  const openInDms = (threadId: string) => {
    router.push(`/dashboard/messages?thread=${threadId}`);
  };

  // Hand off a thread from "the AI is talking" to "I want to talk myself".
  // Flips the thread to human mode on the backend, then navigates to the
  // Messages tab with the thread pre-selected.
  const continueAsHuman = async (threadId: string) => {
    setBusyHit(threadId);
    try {
      await fetch(`${API}/api/persona/threads/${threadId}/mode`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "human" }),
      });
    } catch (e) {
      console.error("Failed to flip thread mode:", e);
    } finally {
      setBusyHit(null);
      router.push(`/dashboard/messages?thread=${threadId}`);
    }
  };

  // From a discovered persona hit: create (or reuse) a human-mode thread, then
  // jump to the Messages tab with it open. This is the "I want to talk to this
  // person myself" path that doesn't involve any AI back-and-forth.
  const openConversationWithPersona = async (hit: PersonaHit) => {
    if (!userId) return;
    setBusyHit(hit.agent_id);
    try {
      const res = await fetch(`${API}/api/persona/${userId}/threads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_agent_id: hit.agent_id,
          target_name: hit.name || "Network Agent",
          mode: "human",
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const tid = data?.thread?.id;
      if (tid) router.push(`/dashboard/messages?thread=${tid}`);
    } catch (e) {
      console.error("Failed to open conversation:", e);
    } finally {
      setBusyHit(null);
    }
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Update the LAST assistant message in the list (the one we're streaming
  // into). Called from every SSE event. Using a functional updater so
  // concurrent events don't step on each other.
  const updateStreamingMessage = (patch: (m: Message) => Message) => {
    setMessages((prev) => {
      if (prev.length === 0) return prev;
      const out = prev.slice();
      const lastIdx = out.length - 1;
      if (out[lastIdx].role !== "assistant") return prev;
      out[lastIdx] = patch(out[lastIdx]);
      return out;
    });
  };

  const handleStreamEvent = (event: any) => {
    switch (event.type) {
      case "text":
        updateStreamingMessage((m) => ({
          ...m,
          content: (m.content || "") + (event.delta || ""),
        }));
        break;

      case "thinking":
        updateStreamingMessage((m) => ({
          ...m,
          thinking: (m.thinking || "") + (event.delta || ""),
        }));
        break;

      case "tool_call_start":
        updateStreamingMessage((m) => ({
          ...m,
          toolCalls: [
            ...(m.toolCalls || []),
            {
              id: event.id,
              name: event.name,
              argsText: "",
              status: "running",
            },
          ],
        }));
        break;

      case "tool_call_args":
        updateStreamingMessage((m) => ({
          ...m,
          toolCalls: (m.toolCalls || []).map((tc) =>
            tc.id === event.id
              ? { ...tc, argsText: tc.argsText + (event.args_delta || "") }
              : tc
          ),
        }));
        break;

      case "tool_call_end":
        updateStreamingMessage((m) => ({
          ...m,
          toolCalls: (m.toolCalls || []).map((tc) =>
            tc.id === event.id
              ? {
                  ...tc,
                  arguments: event.arguments,
                  argsText:
                    typeof event.arguments === "object"
                      ? JSON.stringify(event.arguments)
                      : tc.argsText,
                }
              : tc
          ),
        }));
        break;

      case "tool_result": {
        const isErr =
          typeof event.result === "object" &&
          event.result !== null &&
          "error" in (event.result as Record<string, unknown>);
        updateStreamingMessage((m) => ({
          ...m,
          toolCalls: (m.toolCalls || []).map((tc) =>
            tc.id === event.id
              ? { ...tc, result: event.result, status: isErr ? "error" : "done" }
              : tc
          ),
        }));
        break;
      }

      case "text_to_thinking":
        // The iteration just ended with tool calls, so everything that
        // streamed into `content` during this iteration was actually
        // pre-tool-call reasoning. Move it into the grey thinking
        // dropdown and clear the main content buffer so the next
        // iteration (or the final one) starts fresh.
        updateStreamingMessage((m) => {
          const existing = m.thinking || "";
          const moved = m.content || "";
          if (!moved) return m;
          const sep = existing ? "\n\n" : "";
          return {
            ...m,
            thinking: existing + sep + moved,
            content: "",
          };
        });
        break;

      case "error":
        updateStreamingMessage((m) => ({
          ...m,
          error: event.message || "stream error",
        }));
        break;

      case "done":
        setConversationId(event.conversation_id);
        updateStreamingMessage((m) => ({
          ...m,
          content: event.reply || m.content,
          actions: event.actions_taken,
          streaming: false,
        }));
        break;
    }
  };

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: Message = {
      role: "user",
      content: text,
      timestamp: new Date(),
    };
    const placeholder: Message = {
      role: "assistant",
      content: "",
      thinking: "",
      toolCalls: [],
      streaming: true,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg, placeholder]);
    setInput("");
    setLoading(true);

    try {
      // Auth header — same pattern as lib/api.ts
      const sb = getSupabase();
      const {
        data: { session },
      } = await sb.auth.getSession();

      const res = await fetch(`${API}/api/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(session?.access_token
            ? { Authorization: `Bearer ${session.access_token}` }
            : {}),
        },
        body: JSON.stringify({
          message: text,
          conversation_id: conversationId,
        }),
      });

      if (!res.ok || !res.body) {
        const errText = await res.text().catch(() => "request failed");
        throw new Error(errText);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      // Parse SSE frames: events are separated by blank lines (\n\n).
      // Each frame contains one or more lines prefixed with "data: ".
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sepIdx: number;
        while ((sepIdx = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, sepIdx);
          buffer = buffer.slice(sepIdx + 2);

          // A frame can have multiple lines; concatenate the data lines.
          const dataLines: string[] = [];
          for (const line of frame.split("\n")) {
            if (line.startsWith("data: ")) dataLines.push(line.slice(6));
          }
          if (dataLines.length === 0) continue;

          const payload = dataLines.join("\n");
          try {
            const event = JSON.parse(payload);
            handleStreamEvent(event);
          } catch (e) {
            console.error("Failed to parse SSE frame:", payload, e);
          }
        }
      }

      // Ensure the streaming flag is cleared even if `done` never fired.
      updateStreamingMessage((m) => ({ ...m, streaming: false }));
    } catch (err) {
      updateStreamingMessage((m) => ({
        ...m,
        error: err instanceof Error ? err.message : String(err),
        streaming: false,
      }));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        background: "var(--bg-base)",
      }}
    >
      {/* ── Header ──────────────────────────────────────── */}
      <div className="topbar" style={{ justifyContent: "space-between" }}>
        <div>
          <h1
            style={{
              fontFamily: "Syne, sans-serif",
              fontSize: "15px",
              fontWeight: 700,
              color: "var(--text-primary)",
            }}
          >
            AI Chat
          </h1>
          <p
            style={{
              fontFamily: "IBM Plex Mono, monospace",
              fontSize: "10px",
              color: "var(--text-muted)",
              letterSpacing: "0.5px",
              marginTop: "2px",
            }}
          >
            AGENT INTERFACE · ACTIVE
          </p>
        </div>
        <div className="status-pill">
          <span className="status-dot" />
          Online
        </div>
      </div>

      {/* ── Messages ────────────────────────────────────── */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "24px",
          display: "flex",
          flexDirection: "column",
          gap: "16px",
        }}
      >
        {messages.length === 0 && (
          <div
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: "16px",
            }}
          >
            {/* AI Avatar */}
            <div
              className="animate-float"
              style={{
                width: "56px",
                height: "56px",
                borderRadius: "var(--r-md)",
                background:
                  "linear-gradient(135deg, var(--accent-teal), var(--accent-blue))",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontFamily: "Syne, sans-serif",
                fontWeight: 800,
                fontSize: "24px",
                color: "var(--bg-void)",
                boxShadow: "var(--glow-teal)",
              }}
            >
              Z
            </div>
            <p
              style={{
                color: "var(--text-secondary)",
                fontSize: "14px",
                textAlign: "center",
                maxWidth: "380px",
                lineHeight: 1.6,
              }}
            >
              Start a conversation with your AI agent.
            </p>
            <p
              className="section-label"
              style={{ marginTop: "4px" }}
            >
              SUGGESTED COMMANDS
            </p>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "8px",
                width: "100%",
                maxWidth: "400px",
              }}
            >
              {[
                "Post a tweet about AI agents",
                "Schedule a meeting tomorrow at 3pm",
                "Show my upcoming calendar events",
              ].map((suggestion, i) => (
                <button
                  key={i}
                  onClick={() => setInput(suggestion)}
                  className="card"
                  style={{
                    textAlign: "left",
                    padding: "12px 16px",
                    fontSize: "13px",
                    color: "var(--text-secondary)",
                    fontFamily: "DM Sans, sans-serif",
                  }}
                >
                  <span style={{ color: "var(--accent-teal)", marginRight: "8px", fontFamily: "IBM Plex Mono, monospace", fontSize: "11px" }}>→</span>
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
              gap: "12px",
              animation: "slideIn 0.2s ease",
            }}
          >
            {/* AI Avatar */}
            {msg.role === "assistant" && (
              <div className="msg-avatar">Z</div>
            )}

            <div
              className={
                msg.role === "user" ? "msg-bubble-user" : "msg-bubble-ai"
              }
            >
              {/* ── Thinking / reasoning stream (collapsed grey dropdown) ── */}
              {msg.role === "assistant" && msg.thinking && (() => {
                const expanded = expandedThinking.has(i);
                const previewLine = lastThinkingLine(msg.thinking);
                return (
                  <div
                    style={{
                      marginBottom: "12px",
                      background: "rgba(148, 163, 184, 0.06)",
                      border: "1px solid var(--border-subtle)",
                      borderRadius: "var(--r-sm)",
                      overflow: "hidden",
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => toggleThinking(i)}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "10px",
                        width: "100%",
                        padding: "8px 12px",
                        background: "transparent",
                        border: "none",
                        cursor: "pointer",
                        textAlign: "left",
                        color: "var(--text-muted)",
                        fontFamily: "IBM Plex Mono, monospace",
                        fontSize: "10px",
                        letterSpacing: "0.4px",
                        textTransform: "uppercase",
                      }}
                    >
                      <span
                        style={{
                          display: "inline-block",
                          transform: expanded ? "rotate(90deg)" : "rotate(0deg)",
                          transition: "transform 0.15s ease",
                          width: "8px",
                          textAlign: "center",
                        }}
                      >
                        ▸
                      </span>
                      <span>
                        {msg.streaming ? "Thinking" : "Thought process"}
                      </span>
                      {/* One-line preview when collapsed — updates live as the
                          reasoning streams in. */}
                      {!expanded && previewLine && (
                        <span
                          style={{
                            flex: 1,
                            marginLeft: "6px",
                            textTransform: "none",
                            letterSpacing: 0,
                            fontFamily: "DM Sans, sans-serif",
                            fontSize: "11.5px",
                            color: "var(--text-muted)",
                            fontStyle: "italic",
                            opacity: 0.8,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                            minWidth: 0,
                          }}
                        >
                          {previewLine}
                        </span>
                      )}
                    </button>
                    {expanded && (
                      <div
                        style={{
                          padding: "8px 12px 12px 28px",
                          borderTop: "1px solid var(--border-subtle)",
                          fontFamily: "DM Sans, sans-serif",
                          fontSize: "11.5px",
                          lineHeight: 1.6,
                          color: "var(--text-muted)",
                          whiteSpace: "pre-wrap",
                          maxHeight: "320px",
                          overflowY: "auto",
                        }}
                      >
                        {msg.thinking}
                      </div>
                    )}
                  </div>
                );
              })()}

              {/* ── Live tool-call chips (while streaming) ── */}
              {msg.role === "assistant" && msg.toolCalls && msg.toolCalls.length > 0 && msg.streaming && (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: "4px",
                    marginBottom: "10px",
                  }}
                >
                  {msg.toolCalls.map((tc) => (
                    <div
                      key={tc.id}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "8px",
                        padding: "5px 10px",
                        borderRadius: "999px",
                        background:
                          tc.status === "error"
                            ? "rgba(255, 95, 109, 0.08)"
                            : tc.status === "done"
                            ? "rgba(0, 212, 180, 0.08)"
                            : "rgba(96, 165, 250, 0.08)",
                        border:
                          tc.status === "error"
                            ? "1px solid rgba(255, 95, 109, 0.30)"
                            : tc.status === "done"
                            ? "1px solid rgba(0, 212, 180, 0.30)"
                            : "1px solid rgba(96, 165, 250, 0.30)",
                        fontFamily: "IBM Plex Mono, monospace",
                        fontSize: "10.5px",
                        color:
                          tc.status === "error"
                            ? "var(--accent-coral)"
                            : tc.status === "done"
                            ? "var(--accent-teal)"
                            : "var(--accent-blue)",
                        width: "fit-content",
                        maxWidth: "100%",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      <span>
                        {tc.status === "done"
                          ? "✓"
                          : tc.status === "error"
                          ? "✗"
                          : "⚙"}
                      </span>
                      <span style={{ fontWeight: 600 }}>{tc.name}</span>
                      {tc.status === "running" && (
                        <span style={{ opacity: 0.7 }}>running…</span>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Empty-state indicator: while streaming and nothing has arrived yet */}
              {msg.role === "assistant" &&
                msg.streaming &&
                !msg.content &&
                !msg.thinking &&
                (!msg.toolCalls || msg.toolCalls.length === 0) && (
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "6px",
                      fontSize: "11px",
                      color: "var(--text-muted)",
                      fontFamily: "IBM Plex Mono, monospace",
                    }}
                  >
                    <span>waiting for response</span>
                    <span style={{ animation: "typingDot 1.2s ease infinite" }}>●</span>
                    <span style={{ animation: "typingDot 1.2s ease 0.2s infinite" }}>●</span>
                    <span style={{ animation: "typingDot 1.2s ease 0.4s infinite" }}>●</span>
                  </div>
                )}

              {(msg.content || !msg.streaming) && (
                <div className="markdown-content">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {msg.content}
                  </ReactMarkdown>
                  {msg.streaming && msg.content && (
                    <span
                      style={{
                        display: "inline-block",
                        width: "7px",
                        height: "14px",
                        marginLeft: "2px",
                        background: "var(--accent-teal)",
                        animation: "typingDot 1s ease infinite",
                        verticalAlign: "middle",
                      }}
                    />
                  )}
                </div>
              )}

              {msg.error && (
                <p
                  style={{
                    marginTop: "8px",
                    fontSize: "11px",
                    color: "var(--accent-coral)",
                    fontFamily: "DM Sans, sans-serif",
                  }}
                >
                  ⚠ {msg.error}
                </p>
              )}

              {/* ── Persona discovery cards ── */}
              {(() => {
                const hits = extractPersonaHits(msg.actions);
                if (hits.length === 0) return null;
                return (
                  <div style={{ marginTop: "12px", display: "flex", flexDirection: "column", gap: "8px" }}>
                    <p className="section-label">DISCOVERED ON ZYND NETWORK</p>
                    {hits.map((hit) => (
                      <div
                        key={hit.agent_id}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: "12px",
                          padding: "12px 14px",
                          borderRadius: "var(--r-md)",
                          background: "var(--bg-surface)",
                          border: "1px solid var(--border-default)",
                        }}
                      >
                        <div
                          style={{
                            width: "36px",
                            height: "36px",
                            borderRadius: "var(--r-sm)",
                            background: "linear-gradient(135deg, var(--accent-blue), var(--accent-purple))",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            fontFamily: "Syne, sans-serif",
                            fontWeight: 800,
                            fontSize: "14px",
                            color: "#fff",
                            flexShrink: 0,
                          }}
                        >
                          {(hit.name || "Z").charAt(0).toUpperCase()}
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <p style={{ fontFamily: "DM Sans, sans-serif", fontSize: "13px", fontWeight: 500, color: "var(--text-primary)" }}>
                            {hit.name || "Unknown Persona"}
                          </p>
                          <p style={{ fontFamily: "IBM Plex Mono, monospace", fontSize: "10px", color: "var(--text-muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                            {hit.description || hit.agent_id}
                          </p>
                        </div>
                        <button
                          onClick={() => openConversationWithPersona(hit)}
                          disabled={busyHit === hit.agent_id || !userId}
                          className="btn-primary"
                          style={{ padding: "8px 12px", fontSize: "11px", flexShrink: 0 }}
                        >
                          {busyHit === hit.agent_id ? "Opening…" : "Open Conversation →"}
                        </button>
                      </div>
                    ))}
                  </div>
                );
              })()}

              {/* ── Hand-off cards (AI initiated a thread or proposal) ── */}
              {(() => {
                const handoffs = extractHandoffs(msg.actions);
                if (handoffs.length === 0) return null;
                return (
                  <div style={{ marginTop: "12px", display: "flex", flexDirection: "column", gap: "8px" }}>
                    {handoffs.map((h) => {
                      const isMeeting = h.source_tool === "propose_meeting";
                      // For meetings: keep the thread in agent mode (it's automation)
                      // and just navigate. For DM hand-offs: flip to human mode.
                      const onClick = () =>
                        isMeeting ? openInDms(h.thread_id) : continueAsHuman(h.thread_id);
                      const ctaLabel = isMeeting
                        ? "View meeting in DMs →"
                        : "Continue in DMs as yourself →";
                      const headline =
                        h.source_tool === "request_connection"
                          ? `Connection request sent${h.partner_name ? ` to ${h.partner_name}` : ""}.`
                          : isMeeting
                          ? `Meeting proposal sent${h.partner_name ? ` to ${h.partner_name}` : ""}.`
                          : `Message delivered${h.partner_name ? ` to ${h.partner_name}` : ""}.`;
                      const subline = isMeeting
                        ? "Both sides will see the proposal. They can accept, counter, or decline from the thread."
                        : "The conversation is currently in AI-handling mode. Take it over to reply yourself.";
                      return (
                        <div
                          key={`${h.source_tool}-${h.thread_id}`}
                          style={{
                            padding: "14px 16px",
                            borderRadius: "var(--r-md)",
                            background: "rgba(0, 212, 180, 0.06)",
                            border: "1px solid rgba(0, 212, 180, 0.25)",
                          }}
                        >
                          <p style={{ fontFamily: "DM Sans, sans-serif", fontSize: "13px", color: "var(--text-primary)", marginBottom: "4px" }}>
                            {isMeeting && "📅 "}{headline}
                          </p>
                          <p style={{ fontFamily: "IBM Plex Mono, monospace", fontSize: "10px", color: "var(--text-muted)", marginBottom: "10px" }}>
                            {subline}
                          </p>
                          <button
                            onClick={onClick}
                            disabled={busyHit === h.thread_id}
                            className="btn-primary"
                            style={{ padding: "8px 14px", fontSize: "11px" }}
                          >
                            {busyHit === h.thread_id ? "Opening…" : ctaLabel}
                          </button>
                        </div>
                      );
                    })}
                  </div>
                );
              })()}

              {/* Show actions taken */}
              {msg.actions && msg.actions.length > 0 && (
                <div
                  style={{
                    marginTop: "12px",
                    paddingTop: "10px",
                    borderTop: "1px solid var(--border-subtle)",
                  }}
                >
                  <p className="section-label" style={{ marginBottom: "8px" }}>
                    ACTIONS PERFORMED
                  </p>
                  {msg.actions.map((action, j) => (
                    <details
                      key={j}
                      style={{
                        padding: "8px 12px",
                        borderRadius: "var(--r-sm)",
                        background: "var(--bg-void)",
                        border: "1px solid var(--border-subtle)",
                        fontSize: "12px",
                        fontFamily: "IBM Plex Mono, monospace",
                        color: "var(--accent-teal)",
                        marginBottom: "6px",
                        cursor: "pointer",
                        outline: "none",
                      }}
                    >
                      <summary style={{ outline: "none", userSelect: "none" }}>
                        ✓ {action.tool}
                      </summary>
                      {action.result !== undefined && action.result !== null && (
                        <div
                          style={{
                            marginTop: "8px",
                            padding: "8px",
                            background: "rgba(0,0,0,0.3)",
                            borderRadius: "4px",
                            overflowX: "auto",
                            color: "var(--text-secondary)",
                            fontSize: "11px",
                          }}
                        >
                          <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                            {typeof action.result === "object"
                              ? JSON.stringify(action.result, null, 2)
                              : String(action.result as string)}
                          </pre>
                        </div>
                      )}
                    </details>
                  ))}
                </div>
              )}

              <p className="msg-timestamp" style={{ marginTop: "8px", textAlign: msg.role === "user" ? "right" : "left" }}>
                {msg.timestamp.toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </p>
            </div>
          </div>
        ))}

        <div ref={bottomRef} />
      </div>

      {/* ── Input bar ───────────────────────────────────── */}
      <div
        style={{
          padding: "16px 24px 20px",
          borderTop: "1px solid var(--border-subtle)",
          background: "rgba(13, 17, 23, 0.9)",
          backdropFilter: "blur(8px)",
        }}
      >
        <div
          style={{
            maxWidth: "720px",
            margin: "0 auto",
          }}
        >
          <div className="input-wrap">
            <input
              className="chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  sendMessage();
                }
              }}
              placeholder="Tell your agent what to do…"
              disabled={loading}
            />
            <button
              className="btn-primary"
              onClick={sendMessage}
              disabled={loading || !input.trim()}
              style={{
                padding: "8px 18px",
                fontSize: "12px",
              }}
            >
              {loading ? "..." : "Send"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
