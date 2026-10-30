"use client";

import Link from "next/link";
import { Fragment, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { MessageCircle, X, ArrowUp } from "lucide-react";
import { OPEN_PITCH_EVENT } from "./PitchToBookButton";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface BookingLink {
  label: string;
  url: string;
}

interface ProfileChatWidgetProps {
  handle: string;
  personName: string;
  /** Seeded demo Q&A for the first-win screen (no LLM round-trip). */
  initialMessages?: ChatMessage[];
  defaultOpen?: boolean;
  prompts?: string[];
  bookingLinks?: BookingLink[];
  /** Offer "make your own" after the first answer; the page turns it off for owners and card holders. */
  showCreateCta?: boolean;
  /** The owner asks for a pitch first: `bookingLinks` is empty and the links arrive only from a passed pitch. */
  pitchToBook?: boolean;
}

/** Mirrors cards-api PITCH_MAX_CHARS; the server enforces it. */
const PITCH_MAX_CHARS = 500;

/** The pitch step's panel; once a pitch passes, the panel shows the unlocked links instead. */
type PitchState =
  | { stage: "idle" }
  | { stage: "open"; error?: string }
  | { stage: "checking" }
  | { stage: "declined"; reason: string };

interface UnlockedBooking { reason: string; links: BookingLink[]; }

type PitchResult = { verdict: "pass"; reason: string; links: BookingLink[] } | { verdict: "decline"; reason: string };

function readPitchResult(body: unknown): PitchResult | null {
  if (typeof body !== "object" || body === null) return null;
  const { verdict, reason, links } = body as Record<string, unknown>;
  const text = typeof reason === "string" ? reason : "";
  if (verdict === "decline") return { verdict, reason: text };
  if (verdict !== "pass" || !Array.isArray(links)) return null;
  const valid = links.filter((l): l is BookingLink =>
    typeof l === "object" && l !== null && typeof l.label === "string" && typeof l.url === "string" && isHttp(l.url));
  return { verdict, reason: text, links: valid };
}

const CONTACT_WORDS = ["contact", "email", "call", "meet", "book", "intro", "calendly", "linkedin"];

function isHttp(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

function isContact(text: string): boolean {
  const lowered = text.toLowerCase();
  return CONTACT_WORDS.some((word) => lowered.includes(word));
}

const MAX_HISTORY = 8;

const chipStyle: CSSProperties = {
  fontSize: "12px",
  lineHeight: "1.3",
  color: "#1a1a1a",
  background: "#fff",
  border: "1px solid #E0E0D8",
  borderRadius: "999px",
  padding: "6px 10px",
  cursor: "pointer",
  textDecoration: "none",
};

function linkify(text: string): ReactNode {
  const re = /(https?:\/\/[^\s<>"']+)/g;
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index));
    let url = match[0];
    const trailing = url.match(/[.,;:!?)]+$/)?.[0];
    if (trailing) url = url.slice(0, -trailing.length);
    out.push(
      <a key={key++} href={url} target="_blank" rel="noopener noreferrer" style={{ color: "#4f46e5", textDecoration: "underline" }}>
        {url}
      </a>
    );
    last = match.index + match[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function ProfileChatWidget({
  handle,
  personName,
  initialMessages,
  defaultOpen = false,
  prompts = [],
  bookingLinks = [],
  showCreateCta = false,
  pitchToBook = false,
}: ProfileChatWidgetProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>(() => initialMessages ?? []);
  const [sending, setSending] = useState(false);
  const [introReady, setIntroReady] = useState(false);
  // Pinned under the first real answer so the CTA appears once per session, not after every reply.
  const [createCtaAfter, setCreateCtaAfter] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const seededRef = useRef(false);
  const [pitch, setPitch] = useState<PitchState>({ stage: "idle" });
  const [pitchText, setPitchText] = useState("");
  const [unlocked, setUnlocked] = useState<UnlockedBooking | null>(null);
  const pitchRef = useRef<HTMLTextAreaElement>(null);
  const firstName = personName.split(" ")[0];
  const visibleLinks = bookingLinks.length > 0 ? bookingLinks : unlocked?.links ?? [];
  const canPitch = pitchToBook && !unlocked;

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 80);
  }, [open]);

  useEffect(() => {
    if (seededRef.current || !initialMessages?.length) return;
    seededRef.current = true;
    setMessages(initialMessages);
  }, [initialMessages]);

  useEffect(() => {
    const openChat = () => setOpen(true);
    const markIntro = () => setIntroReady(true);
    const openPitch = () => {
      setOpen(true);
      setPitch({ stage: "open" });
      setTimeout(() => pitchRef.current?.focus(), 80);
    };
    window.addEventListener("zynd:open-profile-chat", openChat);
    window.addEventListener("zynd:intro-ready", markIntro);
    window.addEventListener(OPEN_PITCH_EVENT, openPitch);
    return () => {
      window.removeEventListener("zynd:open-profile-chat", openChat);
      window.removeEventListener("zynd:intro-ready", markIntro);
      window.removeEventListener(OPEN_PITCH_EVENT, openPitch);
    };
  }, []);

  function startPitch() {
    setPitch({ stage: "open" });
    setTimeout(() => pitchRef.current?.focus(), 80);
  }

  function backToChat() {
    setPitch({ stage: "idle" });
    setTimeout(() => inputRef.current?.focus(), 80);
  }

  async function submitPitch() {
    const text = pitchText.trim();
    if (!text || pitch.stage === "checking") return;
    setPitch({ stage: "checking" });
    try {
      const res = await fetch("/api/chat/pitch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ handle, pitch: text }),
      });
      const body: unknown = await res.json().catch(() => null);
      if (!res.ok) {
        const error = typeof body === "object" && body !== null && typeof (body as { error?: unknown }).error === "string"
          ? (body as { error: string }).error : "Couldn't check your pitch right now.";
        setPitch({ stage: "open", error });
        return;
      }
      const result = readPitchResult(body);
      if (!result) {
        setPitch({ stage: "open", error: "Couldn't check your pitch right now." });
      } else if (result.verdict === "pass") {
        setUnlocked({ reason: result.reason, links: result.links });
        setPitch({ stage: "open" });
      } else {
        setPitch({ stage: "declined", reason: result.reason });
      }
    } catch {
      setPitch({ stage: "open", error: "Couldn't reach the assistant. Check your connection and try again." });
    }
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }

  async function sendText(raw: string) {
    const text = raw.trim();
    if (!text || sending) return;

    const history = messages.slice(-MAX_HISTORY);
    const nextMessages: ChatMessage[] = [
      ...messages,
      { role: "user", content: text },
      { role: "assistant", content: "" },
    ];
    setMessages(nextMessages);
    setInput("");
    setSending(true);
    scrollToBottom();

    const assistantIndex = nextMessages.length - 1;

    try {
      const res = await fetch("/api/chat/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          handle,
          messages: [...history, { role: "user", content: text }],
        }),
      });

      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({})) as { error?: string };
        setMessages((prev) => {
          const copy = [...prev];
          copy[assistantIndex] = { role: "assistant", content: err.error ?? "Unavailable right now." };
          return copy;
        });
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let pending = "";
      let textAcc = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        pending += decoder.decode(value, { stream: true });

        const lines = pending.split("\n");
        pending = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6).trim();
          if (payload === "[DONE]") break;
          try {
            const json = JSON.parse(payload) as { response?: string };
            if (json.response) textAcc += json.response;
          } catch { /* skip */ }
        }

        if (textAcc) {
          const content = textAcc;
          setMessages((prev) => {
            const copy = [...prev];
            copy[assistantIndex] = { role: "assistant", content };
            return copy;
          });
          scrollToBottom();
        }
      }

      if (!textAcc) {
        setMessages((prev) => {
          const copy = [...prev];
          copy[assistantIndex] = { role: "assistant", content: "No response — try again." };
          return copy;
        });
      } else if (showCreateCta) {
        setCreateCtaAfter((current) => current ?? assistantIndex);
      }
    } catch {
      setMessages((prev) => {
        const copy = [...prev];
        copy[assistantIndex] = { role: "assistant", content: "Something went wrong." };
        return copy;
      });
    } finally {
      setSending(false);
      scrollToBottom();
    }
  }

  function send() {
    void sendText(input);
  }

  if (!open) {
    return (
      <>
      <button
        className="pf-chat-fab"
        type="button"
        aria-label={`Ask ${personName}'s AI assistant`}
        onClick={() => setOpen(true)}
        style={{
          position: "fixed", bottom: "24px", right: "24px", zIndex: 50,
          width: "48px", height: "48px", borderRadius: "50%",
          background: "#0B0B0B", color: "#fff", border: "none",
          display: "flex", alignItems: "center", justifyContent: "center",
          cursor: "pointer", boxShadow: "0 4px 20px rgba(0,0,0,0.25)",
          transition: "transform 0.15s, box-shadow 0.15s",
        }}
        onMouseEnter={e => { (e.target as HTMLElement).style.transform = "scale(1.08)"; }}
        onMouseLeave={e => { (e.target as HTMLElement).style.transform = "scale(1)"; }}
      >
        <MessageCircle size={20} />
      </button>
      <style>{`@media (max-width: 820px) { .pf-chat-fab { bottom: calc(76px + env(safe-area-inset-bottom, 0px)) !important; right: 16px !important; } }`}</style>
      </>
    );
  }

  const pitchChecking = pitch.stage === "checking";
  const pitchReady = pitchText.trim().length > 0 && !pitchChecking;
  const pitchPanel = (
    <section aria-label={`Pitch ${firstName} for a call`} data-testid="pitch-step" style={{
      padding: "12px", background: "#fff", borderTop: "1px solid #E8E8E1",
      display: "flex", flexDirection: "column", gap: 8, flexShrink: 0,
    }}>
      {!unlocked && (pitch.stage === "open" || pitch.stage === "checking") && (
        <>
          <label htmlFor="profile-chat-pitch" style={{ fontSize: "13px", fontWeight: 600, color: "#1a1a1a" }}>
            Why do you want to meet {firstName}?
          </label>
          <p id="profile-chat-pitch-hint" style={{ margin: 0, fontSize: "11px", lineHeight: 1.5, color: "#56565d" }}>
            {firstName} asks for a short pitch before sharing their calendar. The assistant checks it against what they&apos;re looking for. Your pitch isn&apos;t saved.
          </p>
          <textarea
            id="profile-chat-pitch"
            ref={pitchRef}
            value={pitchText}
            onChange={(e) => setPitchText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void submitPitch(); }
            }}
            maxLength={PITCH_MAX_CHARS}
            rows={3}
            disabled={pitchChecking}
            aria-describedby="profile-chat-pitch-hint"
            placeholder="1–3 sentences: who you are and what you'd like to talk about"
            style={{
              resize: "none", border: "1px solid #E0E0D8", borderRadius: "12px", padding: "9px 12px",
              fontSize: "13px", lineHeight: "1.45", color: "#1a1a1a", background: "#F7F7F4",
              outline: "none", fontFamily: "inherit",
            }}
          />
          {pitch.stage === "open" && pitch.error && (
            <p role="alert" style={{ margin: 0, fontSize: "12px", color: "#B91C1C" }}>{pitch.error}</p>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button type="button" onClick={backToChat} disabled={pitchChecking} style={{ ...chipStyle, border: "none", background: "none", paddingLeft: 0 }}>
              Back to chat
            </button>
            <span aria-hidden="true" style={{ marginLeft: "auto", fontSize: "11px", color: "#999" }}>
              {pitchText.length}/{PITCH_MAX_CHARS}
            </span>
            <button
              type="button"
              onClick={() => void submitPitch()}
              disabled={!pitchReady}
              style={{
                ...chipStyle, border: "none", fontWeight: 600,
                background: pitchReady ? "#0B0B0B" : "#E8E8E1", color: pitchReady ? "#fff" : "#999",
                cursor: pitchReady ? "pointer" : "default",
              }}
            >
              {pitchChecking ? "Checking…" : "Send pitch"}
            </button>
          </div>
        </>
      )}
      {unlocked && (
        <>
          <p role="status" style={{ margin: 0, fontSize: "13px", lineHeight: 1.5, color: "#1a1a1a" }}>{unlocked.reason}</p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {unlocked.links.map((link) => (
              <a key={link.url} href={link.url} target="_blank" rel="noopener noreferrer"
                style={{ ...chipStyle, background: "#0B0B0B", color: "#fff", border: "none", fontWeight: 600 }}>
                Book on {link.label}
              </a>
            ))}
            <button type="button" onClick={backToChat} style={chipStyle}>Back to chat</button>
          </div>
        </>
      )}
      {!unlocked && pitch.stage === "declined" && (
        <>
          <p role="status" style={{ margin: 0, fontSize: "13px", lineHeight: 1.5, color: "#1a1a1a" }}>{pitch.reason}</p>
          <p style={{ margin: 0, fontSize: "11px", lineHeight: 1.5, color: "#56565d" }}>
            You can send a new pitch in about 10 minutes, or reach {firstName} another way.
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {introReady && (
              <button type="button" onClick={() => window.dispatchEvent(new Event("zynd:open-intro"))} style={chipStyle}>
                Request an intro
              </button>
            )}
            <button type="button" onClick={backToChat} style={chipStyle}>Ask a question instead</button>
          </div>
        </>
      )}
    </section>
  );

  return (
    <div className="pf-chat-panel" style={{
      position: "fixed", bottom: "24px", right: "24px", zIndex: 50,
      width: "360px", maxWidth: "calc(100vw - 32px)",
      height: "520px", display: "flex", flexDirection: "column",
      borderRadius: "20px", overflow: "hidden",
      background: "#fff",
      boxShadow: "0 8px 40px rgba(0,0,0,0.18), 0 2px 8px rgba(0,0,0,0.08)",
      border: "1px solid rgba(0,0,0,0.08)",
    }}>

      {/* Header */}
      <div style={{
        padding: "14px 16px", background: "#0B0B0B", color: "#fff",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexShrink: 0,
      }}>
        <div>
          <div style={{ fontSize: "14px", fontWeight: 600, letterSpacing: "-0.01em" }}>{personName.split(" ")[0]}&apos;s AI assistant</div>
          <div style={{ fontSize: "11px", color: "rgba(255,255,255,0.5)", marginTop: "1px" }}>Answers from this card — not {personName.split(" ")[0]}</div>
        </div>
        <button
          type="button"
          onClick={() => setOpen(false)}
          style={{ background: "none", border: "none", color: "rgba(255,255,255,0.5)", cursor: "pointer", padding: "4px", display: "flex", transition: "color 0.12s" }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = "#fff"; }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = "rgba(255,255,255,0.5)"; }}
        >
          <X size={16} />
        </button>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        style={{
          flex: 1, overflowY: "auto", padding: "16px",
          display: "flex", flexDirection: "column", gap: "10px",
          background: "#FAFAF8",
        }}
      >
        {messages.length === 0 && (
          <div style={{ margin: "auto", textAlign: "center", color: "#999", fontSize: "13px", width: "100%" }}>
            <div style={{ fontSize: "22px", marginBottom: "8px" }}>💬</div>
            Ask anything about {personName.split(" ")[0]} — I&apos;m an AI assistant
            <div style={{ marginTop: 6, fontSize: "11px" }}>
              answering from this card&apos;s public profile
            </div>
            {(prompts.length > 0 || visibleLinks.length > 0 || introReady || canPitch) && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, justifyContent: "center", marginTop: 14 }}>
                {prompts.slice(0, 3).map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    disabled={sending}
                    onClick={() => void sendText(prompt)}
                    style={chipStyle}
                  >
                    {prompt}
                  </button>
                ))}
                {(visibleLinks.length > 0 || introReady) && (
                  <button
                    type="button"
                    disabled={sending}
                    onClick={() => void sendText("How do I contact them?")}
                    style={chipStyle}
                  >
                    How do I contact them?
                  </button>
                )}
                {canPitch && (
                  <button type="button" disabled={sending} onClick={startPitch} style={chipStyle}>
                    Book a call
                  </button>
                )}
              </div>
            )}
          </div>
        )}
        {messages.map((m, i) => (
          <Fragment key={i}>
          <div style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
            <div style={{
              maxWidth: "82%",
              padding: "9px 13px",
              borderRadius: m.role === "user" ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
              background: m.role === "user" ? "#0B0B0B" : "#fff",
              color: m.role === "user" ? "#fff" : "#1a1a1a",
              fontSize: "13px", lineHeight: "1.5",
              border: m.role === "assistant" ? "1px solid #E8E8E1" : "none",
              boxShadow: m.role === "assistant" ? "0 1px 3px rgba(0,0,0,0.05)" : "none",
              wordBreak: "break-word",
            }}>
              {m.content ? (
                m.role === "assistant" ? linkify(m.content) : m.content
              ) : (
                <span style={{ display: "inline-flex", gap: "3px", color: "#999" }}>
                  <span style={{ animation: "dot 1.2s infinite", animationDelay: "0ms" }}>•</span>
                  <span style={{ animation: "dot 1.2s infinite", animationDelay: "200ms" }}>•</span>
                  <span style={{ animation: "dot 1.2s infinite", animationDelay: "400ms" }}>•</span>
                  <style>{`@keyframes dot { 0%,80%,100%{opacity:.3} 40%{opacity:1} }`}</style>
                </span>
              )}
            </div>
          </div>
          {i === createCtaAfter && (
            <div data-testid="ask-card-create-cta" style={{
              alignSelf: "flex-start", maxWidth: "82%",
              padding: "8px 12px", borderRadius: "12px",
              background: "#fff", border: "1px dashed #E0E0D8",
              fontSize: "12px", lineHeight: "1.45", color: "#56565d",
            }}>
              Want an AI that answers like this for you?{" "}
              {/* prefetch off: proxy.ts records ?ref= on prefetches too, which would credit ask_card without a click. */}
              <Link href="/create?ref=ask_card" prefetch={false} style={{ color: "#4f46e5", fontWeight: 600, textDecoration: "underline" }}>
                Create your card
              </Link>
            </div>
          )}
          </Fragment>
        ))}
      </div>

      {pitch.stage === "idle" && messages.some((m) => m.role === "user" && isContact(m.content)) && (visibleLinks.length > 0 || introReady || canPitch) && (
        <div style={{
          padding: "8px 12px", background: "#fff", borderTop: "1px solid #E8E8E1",
          display: "flex", flexWrap: "wrap", gap: 6, flexShrink: 0,
        }}>
          {canPitch && (
            <button type="button" onClick={startPitch} style={chipStyle}>
              Pitch to book a call
            </button>
          )}
          {visibleLinks.filter((link) => isHttp(link.url)).map((link) => (
            <a
              key={link.url}
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              style={chipStyle}
            >
              Book on {link.label}
            </a>
          ))}
          {introReady && (
            <button
              type="button"
              onClick={() => window.dispatchEvent(new Event("zynd:open-intro"))}
              style={chipStyle}
            >
              Request an intro
            </button>
          )}
        </div>
      )}

      {pitch.stage !== "idle" ? pitchPanel : (
      <>
      {/* Input */}
      <p id="profile-chat-history-notice" style={{ margin: 0, padding: "8px 12px", background: "#fff", color: "#56565d", fontSize: 11, lineHeight: 1.5 }}>
        Questions are saved for the profile owner to review. Common contact details are redacted. Avoid sharing private information.
      </p>
      <div style={{
        padding: "10px 12px", background: "#fff",
        borderTop: "1px solid #E8E8E1", display: "flex", alignItems: "flex-end", gap: "8px",
        flexShrink: 0,
      }}>
        <textarea
          ref={inputRef}
          value={input}
          onChange={e => {
            setInput(e.target.value);
            e.target.style.height = "auto";
            e.target.style.height = Math.min(e.target.scrollHeight, 100) + "px";
          }}
          onKeyDown={e => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
          }}
          placeholder="Ask a question…"
          aria-label="Your question"
          aria-describedby="profile-chat-history-notice"
          disabled={sending}
          rows={1}
          style={{
            flex: 1, resize: "none", border: "1px solid #E0E0D8",
            borderRadius: "12px", padding: "9px 12px",
            fontSize: "13px", lineHeight: "1.45",
            color: "#1a1a1a", background: "#F7F7F4",
            outline: "none", fontFamily: "inherit",
            overflowY: "hidden", minHeight: "38px",
            transition: "border-color 0.12s",
          }}
          onFocus={e => { e.target.style.borderColor = "#0B0B0B"; }}
          onBlur={e => { e.target.style.borderColor = "#E0E0D8"; }}
        />
        <button
          type="button"
          onClick={send}
          disabled={sending || !input.trim()}
          style={{
            width: "36px", height: "36px", borderRadius: "10px", flexShrink: 0,
            background: input.trim() && !sending ? "#0B0B0B" : "#E8E8E1",
            color: input.trim() && !sending ? "#fff" : "#999",
            border: "none", cursor: input.trim() && !sending ? "pointer" : "default",
            display: "flex", alignItems: "center", justifyContent: "center",
            transition: "background 0.12s, color 0.12s",
          }}
        >
          <ArrowUp size={16} />
        </button>
      </div>
      </>
      )}
      <style>{`
        @media (max-width: 820px) {
          .pf-chat-panel {
            left: 12px !important;
            right: 12px !important;
            bottom: 12px !important;
            width: auto !important;
            height: min(520px, calc(100dvh - 24px)) !important;
            max-width: none !important;
          }
          .pf-chat-fab {
            bottom: 16px !important;
            right: 16px !important;
          }
        }
      `}</style>
    </div>
  );
}
