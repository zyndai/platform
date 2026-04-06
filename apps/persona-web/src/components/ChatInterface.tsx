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
      }}
    >
      {/* ── Header ──────────────────────────────────────── */}
      <div
        style={{
          padding: "20px 32px",
          borderBottom: "1px solid var(--border-color)",
          background: "rgba(10, 10, 15, 0.8)",
          backdropFilter: "blur(12px)",
        }}
      >
        <h1 style={{ fontSize: "1.3rem", fontWeight: 700 }}>AI Chat</h1>
        <p style={{ fontSize: "0.82rem", color: "var(--text-muted)", marginTop: "4px" }}>
          Tell your agent what to do — post tweets, schedule events, send messages.
        </p>
      </div>

      {/* ── Messages ────────────────────────────────────── */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "32px",
          display: "flex",
          flexDirection: "column",
          gap: "20px",
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
            <div
              className="animate-float"
              style={{ fontSize: "3rem", opacity: 0.6 }}
            >
              🤖
            </div>
            <p
              style={{
                color: "var(--text-muted)",
                fontSize: "1rem",
                textAlign: "center",
                maxWidth: "400px",
                lineHeight: 1.6,
              }}
            >
              Start a conversation. Try something like:
            </p>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "8px",
                width: "100%",
                maxWidth: "420px",
              }}
            >
              {[
                '"Post a tweet about AI agents"',
                '"Schedule a meeting tomorrow at 3pm"',
                '"Show my upcoming calendar events"',
              ].map((suggestion, i) => (
                <button
                  key={i}
                  onClick={() => {
                    setInput(suggestion.replace(/"/g, ""));
                  }}
                  style={{
                    padding: "12px 16px",
                    borderRadius: "var(--radius-sm)",
                    background: "rgba(108, 92, 231, 0.06)",
                    border: "1px solid var(--border-color)",
                    color: "var(--text-secondary)",
                    fontSize: "0.85rem",
                    cursor: "pointer",
                    textAlign: "left",
                    transition: "all 0.2s ease",
                    fontFamily: "var(--font-sans)",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = "var(--accent-primary)";
                    e.currentTarget.style.background = "rgba(108, 92, 231, 0.1)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = "var(--border-color)";
                    e.currentTarget.style.background = "rgba(108, 92, 231, 0.06)";
                  }}
                >
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
              animation: "fadeInUp 0.3s ease forwards",
            }}
          >
            <div
              style={{
                maxWidth: "70%",
                padding: "14px 18px",
                borderRadius:
                  msg.role === "user"
                    ? "var(--radius) var(--radius) 4px var(--radius)"
                    : "var(--radius) var(--radius) var(--radius) 4px",
                background:
                  msg.role === "user"
                    ? "linear-gradient(135deg, var(--accent-primary), #8b5cf6)"
                    : "var(--bg-card)",
                border:
                  msg.role === "assistant"
                    ? "1px solid var(--border-color)"
                    : "none",
                color: "#fff",
                fontSize: "0.9rem",
                lineHeight: 1.6,
              }}
            >
              <div className="markdown-content">
                <ReactMarkdown
                  components={{
                    h1: ({node, ...props}) => <h1 style={{ fontSize: '1.8rem', fontWeight: 800, margin: '20px 0 12px', color: '#fff', display: 'block' }} {...props} />,
                    h2: ({node, ...props}) => <h2 style={{ fontSize: '1.4rem', fontWeight: 700, margin: '18px 0 10px', color: '#fff', display: 'block' }} {...props} />,
                    p: ({node, ...props}) => <p style={{ marginBottom: '12px', lineHeight: '1.6', display: 'block' }} {...props} />,
                  }}
                >
                  {msg.content}
                </ReactMarkdown>
              </div>

              {/* Show actions taken */}
              {msg.actions && msg.actions.length > 0 && (
                <div
                  style={{
                    marginTop: "12px",
                    paddingTop: "10px",
                    borderTop: "1px solid rgba(255,255,255,0.1)",
                  }}
                >
                  <p
                    style={{
                      fontSize: "0.72rem",
                      fontWeight: 600,
                      textTransform: "uppercase",
                      letterSpacing: "0.5px",
                      color: "rgba(255,255,255,0.5)",
                      marginBottom: "6px",
                    }}
                  >
                    Actions performed:
                  </p>
                  {msg.actions.map((action, j) => (
                    <details
                      key={j}
                      style={{
                        padding: "8px 12px",
                        borderRadius: "6px",
                        background: "rgba(0,0,0,0.25)",
                        fontSize: "0.78rem",
                        fontFamily: "monospace",
                        color: "var(--success)",
                        marginBottom: "6px",
                        cursor: "pointer",
                        outline: "none",
                      }}
                    >
                      <summary style={{ outline: "none", userSelect: "none" }}>✓ {action.tool}</summary>
                      {action.result !== undefined && action.result !== null && (
                        <div style={{ 
                          marginTop: '8px', 
                          padding: '8px', 
                          background: 'rgba(0,0,0,0.4)', 
                          borderRadius: '4px', 
                          overflowX: 'auto', 
                          color: 'rgba(255,255,255,0.85)', 
                          fontSize: '0.7rem' 
                        }}>
                          <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                            {typeof action.result === 'object' ? JSON.stringify(action.result, null, 2) : String(action.result as any)}
                          </pre>
                        </div>
                      )}
                    </details>
                  ))}
                </div>
              )}

              <p
                style={{
                  fontSize: "0.68rem",
                  color: "rgba(255,255,255,0.35)",
                  marginTop: "8px",
                  textAlign: "right",
                }}
              >
                {msg.timestamp.toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </p>
            </div>
          </div>
        ))}

        {loading && (
          <div style={{ display: "flex", justifyContent: "flex-start" }}>
            <div
              className="shimmer-bg"
              style={{
                padding: "14px 18px",
                borderRadius: "var(--radius) var(--radius) var(--radius) 4px",
                background: "var(--bg-card)",
                border: "1px solid var(--border-color)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  gap: "6px",
                  alignItems: "center",
                }}
              >
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
                  Thinking
                </span>
                <span className="animate-float" style={{ fontSize: "0.6rem" }}>●</span>
                <span className="animate-float" style={{ fontSize: "0.6rem", animationDelay: "0.2s" }}>●</span>
                <span className="animate-float" style={{ fontSize: "0.6rem", animationDelay: "0.4s" }}>●</span>
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Input bar ───────────────────────────────────── */}
      <div
        style={{
          padding: "16px 32px 24px",
          borderTop: "1px solid var(--border-color)",
          background: "rgba(10, 10, 15, 0.9)",
          backdropFilter: "blur(12px)",
        }}
      >
        <div
          style={{
            display: "flex",
            gap: "12px",
            maxWidth: "800px",
            margin: "0 auto",
          }}
        >
          <input
            className="input"
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
            style={{ flex: 1 }}
          />
          <button
            className="btn btn-primary"
            onClick={sendMessage}
            disabled={loading || !input.trim()}
            style={{
              opacity: loading || !input.trim() ? 0.5 : 1,
              minWidth: "100px",
            }}
          >
            {loading ? "…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
