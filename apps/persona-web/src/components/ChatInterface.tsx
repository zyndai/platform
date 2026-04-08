"use client";

import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiPost } from "@/lib/api";

interface Message {
  role: "user" | "assistant";
  content: string;
  actions?: { tool: string; result: unknown }[];
  timestamp: Date;
}

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: Message = {
      role: "user",
      content: text,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await apiPost<{
        reply: string;
        actions_taken: { tool: string; args: unknown; result: unknown }[];
        conversation_id: string;
      }>("/api/chat/message", {
        message: text,
        conversation_id: conversationId,
      });

      setConversationId(res.conversation_id);

      const assistantMsg: Message = {
        role: "assistant",
        content: res.reply,
        actions: res.actions_taken,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      const errorMsg: Message = {
        role: "assistant",
        content: `Sorry, something went wrong: ${err instanceof Error ? err.message : "Unknown error"}`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMsg]);
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
              <div className="markdown-content">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {msg.content}
                </ReactMarkdown>
              </div>

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

        {loading && (
          <div style={{ display: "flex", gap: "12px", animation: "slideIn 0.2s ease" }}>
            <div className="msg-avatar">Z</div>
            <div
              className="msg-bubble-ai"
              style={{ display: "flex", alignItems: "center", gap: "8px" }}
            >
              <span style={{ fontSize: "12px", color: "var(--text-muted)", fontFamily: "IBM Plex Mono, monospace" }}>
                Processing
              </span>
              <span style={{ animation: "typingDot 1.2s ease infinite" }}>●</span>
              <span style={{ animation: "typingDot 1.2s ease 0.2s infinite" }}>●</span>
              <span style={{ animation: "typingDot 1.2s ease 0.4s infinite" }}>●</span>
            </div>
          </div>
        )}

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
