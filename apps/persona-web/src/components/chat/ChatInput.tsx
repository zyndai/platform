"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowUp,
  Plus,
  Mic,
  MicOff,
  SlidersHorizontal,
  FileText,
  Calendar,
  Send,
  ArrowUpRight,
} from "lucide-react";
import { QUICK_PROMPTS } from "./quickPrompts";

function LinkedinIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" {...props}>
      <path d="M20.45 20.45h-3.55v-5.57c0-1.33-.03-3.04-1.85-3.04-1.86 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zm1.78 13.02H3.55V9h3.57v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z" />
    </svg>
  );
}

// Minimal typings for the Web Speech API (not in lib.dom).
type SRResult = {
  isFinal: boolean;
  0: { transcript: string };
};
type SRResultList = ArrayLike<SRResult>;
type SREvent = { results: SRResultList; resultIndex: number };
type SRErrorEvent = { error: string; message?: string };
type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((e: SRErrorEvent) => void) | null;
  onresult: ((e: SREvent) => void) | null;
};
type SRConstructor = new () => SpeechRecognitionLike;

function getSpeechRecognition(): SRConstructor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: SRConstructor;
    webkitSpeechRecognition?: SRConstructor;
  };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

interface SuggestPill {
  label: string;
  send: string;
}

interface ChatInputProps {
  value: string;
  onChange: (next: string) => void;
  onSend: (text: string) => void;
  disabled?: boolean;
  pills?: SuggestPill[];
  placeholder?: string;
  variant?: "v1" | "v2";
}

const MAX_CHARS = 3000;

export default function ChatInput({
  value,
  onChange,
  onSend,
  disabled = false,
  pills,
  placeholder = "Ask your agent anything…  Try /services <query>",
  variant = "v2",
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const hasText = value.trim().length > 0;

  // Popovers for the + (quick prompts) and Tools (connections) buttons.
  const [addOpen, setAddOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const addRef = useRef<HTMLDivElement | null>(null);
  const toolsRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!addOpen && !toolsOpen) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (addOpen && addRef.current && !addRef.current.contains(target)) {
        setAddOpen(false);
      }
      if (toolsOpen && toolsRef.current && !toolsRef.current.contains(target)) {
        setToolsOpen(false);
      }
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setAddOpen(false);
        setToolsOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onEsc);
    };
  }, [addOpen, toolsOpen]);

  // Voice-to-text via Web Speech API.
  //
  // Browser quirk: even with continuous=true, Chrome (and Safari to a lesser
  // extent) auto-ends the recognizer on a few seconds of silence — onend
  // fires and recording stops mid-thought from the user's perspective. The
  // fix is to distinguish a USER-initiated stop (mic button click, unmount)
  // from a BROWSER auto-end, and restart the recognizer in the latter case
  // until the user actually wants to stop.
  //
  // Second quirk: each restarted session emits results from index 0, so we
  // must commit any finalized transcripts into baseValueRef as they arrive.
  // If we only read from e.results at result-time, the next session's
  // interim text would replace everything the previous session captured.
  const [recording, setRecording] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  // Cumulative committed text — built up across session restarts. Interim
  // (in-progress) speech is appended on top of this for display, but only
  // finalized text gets promoted into baseValueRef.
  const baseValueRef = useRef("");
  // Flipped when the user explicitly clicks the mic to stop OR when the
  // component unmounts. While false, onend → auto-restart.
  const userStoppedRef = useRef(false);
  const mountedRef = useRef(true);
  // Pending restart timer + restart-storm detection. If the browser keeps
  // ending sessions back-to-back without giving us any audio in between,
  // restart attempts make things worse — we'd be in a tight loop of
  // failing .start() calls while the user stares at a "recording" mic
  // that captures nothing. We track recent restart timestamps and bail
  // out after 4 consecutive restarts inside a 4-second window.
  const restartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const recentRestartsRef = useRef<number[]>([]);
  // Keep `onChange` reference stable for handlers attached to `recognition`.
  const onChangeRef = useRef(onChange);
  useEffect(() => { onChangeRef.current = onChange; }, [onChange]);

  const clearPendingRestart = () => {
    if (restartTimerRef.current) {
      clearTimeout(restartTimerRef.current);
      restartTimerRef.current = null;
    }
  };

  const stopRecording = useCallback(() => {
    userStoppedRef.current = true;
    clearPendingRestart();
    const r = recognitionRef.current;
    if (!r) return;
    // abort() is more decisive than stop() — releases the audio resource
    // immediately so a follow-up start() doesn't race with cleanup.
    try { r.abort(); } catch { /* ignore */ }
    recognitionRef.current = null;
    setRecording(false);
  }, []);

  const startRecording = useCallback(() => {
    const Ctor = getSpeechRecognition();
    if (!Ctor) {
      setVoiceError(
        "Voice input isn't supported in this browser. Try Chrome, Edge, or Safari.",
      );
      return;
    }
    userStoppedRef.current = false;
    recentRestartsRef.current = [];
    baseValueRef.current = value;

    // Build a recognizer instance bound to the current handlers. Hoisted
    // into a factory so the onend auto-restart path can rebuild a clean
    // session without recursing through startRecording's closure.
    const spawn = (): SpeechRecognitionLike => {
      const r = new Ctor();
      r.lang = "en-US";
      r.continuous = true;
      r.interimResults = true;

      r.onstart = () => {
        setRecording(true);
        setVoiceError(null);
      };

      r.onend = () => {
        recognitionRef.current = null;
        // If the user clicked the mic or we've unmounted, this is a real
        // stop — drop out of recording state.
        if (userStoppedRef.current || !mountedRef.current) {
          setRecording(false);
          return;
        }

        // Restart-storm guard: if we've had 4 onend events inside the
        // last 4 seconds, something is wrong with the audio stack and
        // restarting again will just keep failing silently. Surface a
        // visible error and stop instead of churning forever.
        const now = Date.now();
        recentRestartsRef.current = [
          ...recentRestartsRef.current.filter((t) => now - t < 4000),
          now,
        ];
        if (recentRestartsRef.current.length > 4) {
          userStoppedRef.current = true;
          setRecording(false);
          setVoiceError("Mic kept dropping — try again, or check your input device.");
          return;
        }

        // Otherwise the browser auto-ended the session (silence timeout,
        // no-speech, etc.). Restart after a short delay so the audio
        // resource has time to be released — starting immediately can
        // race with the platform's mic teardown and produce a session
        // that's alive in JS but capturing nothing.
        clearPendingRestart();
        restartTimerRef.current = setTimeout(() => {
          restartTimerRef.current = null;
          if (userStoppedRef.current || !mountedRef.current) return;
          try {
            const next = spawn();
            recognitionRef.current = next;
            next.start();
          } catch {
            setRecording(false);
          }
        }, 250);
      };

      r.onerror = (e) => {
        // Permission denied is a real stop — don't auto-retry, it would
        // just spam the user's deny prompt.
        if (e.error === "not-allowed" || e.error === "service-not-allowed") {
          userStoppedRef.current = true;
          clearPendingRestart();
          setRecording(false);
          recognitionRef.current = null;
          setVoiceError("Mic permission was denied. Allow it in your browser settings.");
          return;
        }
        // "aborted" specifically means we called .abort() — never auto-restart.
        if (e.error === "aborted") {
          userStoppedRef.current = true;
          clearPendingRestart();
          return;
        }
        // Other errors (network, no-speech, audio-capture) are typical
        // during a session — let onend handle the restart.
        if (process.env.NODE_ENV !== "production") {
          // eslint-disable-next-line no-console
          console.debug("[speech] non-fatal error:", e.error);
        }
      };

      r.onresult = (e) => {
        // Real audio came through — reset the storm counter. We're not in
        // a tight failure loop, just normal continuous speech.
        recentRestartsRef.current = [];
        // Walk the result set, separating finalized phrases from in-progress
        // interim text. We commit finalized text to baseValueRef so a
        // mid-recording session restart doesn't lose what was already said.
        let interim = "";
        let final = "";
        for (let i = 0; i < e.results.length; i++) {
          const res = e.results[i];
          if (res.isFinal) final += res[0].transcript;
          else interim += res[0].transcript;
        }
        if (final) {
          const base = baseValueRef.current;
          const sep = base && !/\s$/.test(base) ? " " : "";
          baseValueRef.current = (base + sep + final).slice(0, MAX_CHARS);
        }
        // Compose what the textarea should show right now: committed text
        // + the live interim portion.
        const base = baseValueRef.current;
        const sep = base && !/\s$/.test(base) && interim ? " " : "";
        const displayed = (base + sep + interim).slice(0, MAX_CHARS);
        onChangeRef.current(displayed);
      };

      return r;
    };

    try {
      const r = spawn();
      recognitionRef.current = r;
      r.start();
    } catch {
      // Already started or invalid state — leave UI alone.
    }
  }, [value]);

  const toggleMic = useCallback(() => {
    if (disabled) return;
    if (recording) stopRecording();
    else startRecording();
  }, [disabled, recording, startRecording, stopRecording]);

  // Cleanup: hard-abort any active recognition on unmount, cancel any
  // scheduled restart, and flip the user-stopped flag so an in-flight
  // restart timer that fires after unmount becomes a no-op.
  useEffect(() => {
    return () => {
      mountedRef.current = false;
      userStoppedRef.current = true;
      clearPendingRestart();
      const r = recognitionRef.current;
      if (r) {
        try { r.abort(); } catch { /* ignore */ }
        recognitionRef.current = null;
      }
    };
  }, []);

  // Auto-clear the error after a few seconds so the disclaimer can return.
  useEffect(() => {
    if (!voiceError) return;
    const t = setTimeout(() => setVoiceError(null), 4500);
    return () => clearTimeout(t);
  }, [voiceError]);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const lineHeight = 22;
    const max = lineHeight * 5 + 8;
    ta.style.height = Math.min(ta.scrollHeight, max) + "px";
    ta.style.overflowY = ta.scrollHeight > max ? "auto" : "hidden";
  }, [value]);

  const handleSend = () => {
    const t = value.trim();
    if (!t || disabled) return;
    onSend(t);
  };

  if (variant === "v1") {
    return (
      <div style={{ padding: "16px 16px 20px", width: "100%" }}>
        {pills && pills.length > 0 && (
          <div className="suggest-pills">
            {pills.map((p, i) => (
              <button
                key={i}
                type="button"
                onClick={() => { if (!disabled) onSend(p.send); }}
                disabled={disabled}
              >
                {p.label}
              </button>
            ))}
          </div>
        )}
        <div className={`chat-input-bar ${hasText ? "has-text" : ""}`}>
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder={placeholder}
            disabled={disabled}
            aria-label="Chat with your Persona"
          />
          <button
            type="button"
            className="send-btn"
            onClick={handleSend}
            disabled={!hasText || disabled}
            aria-label="Send"
          >
            <ArrowUp />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-input-frame">
      <div className="chat-input-wrap">
        {pills && pills.length > 0 && (
          <div className="suggest-pills" style={{ marginBottom: 10 }}>
            {pills.map((p, i) => (
              <button
                key={i}
                type="button"
                onClick={() => { if (!disabled) onSend(p.send); }}
                disabled={disabled}
              >
                {p.label}
              </button>
            ))}
          </div>
        )}

        <div className={`chat-input-v2 ${hasText ? "has-text" : ""}`}>
          <div className="chat-input-v2-inner">
            <div className="row-1">
              <textarea
                ref={textareaRef}
                rows={1}
                value={value}
                onChange={(e) => {
                  const next = e.target.value.slice(0, MAX_CHARS);
                  onChange(next);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder={placeholder}
                disabled={disabled}
                aria-label="Chat with your Persona"
              />
              <button
                type="button"
                className="send-btn"
                onClick={handleSend}
                disabled={!hasText || disabled}
                aria-label="Send"
              >
                <ArrowUp />
              </button>
            </div>
            <div className="row-2">
              <div className="tools">
                <div className="tool-popover" ref={addRef}>
                  <button
                    type="button"
                    className={`tool-add ${addOpen ? "open" : ""}`}
                    onClick={() => {
                      setToolsOpen(false);
                      setAddOpen((v) => !v);
                    }}
                    aria-haspopup="menu"
                    aria-expanded={addOpen}
                    aria-label="Quick prompts"
                  >
                    <Plus />
                  </button>
                  {addOpen && (
                    <div className="tool-popover-menu" role="menu">
                      <div className="tool-popover-head">Quick prompts</div>
                      {QUICK_PROMPTS.map((p) => {
                        const Icon = p.icon;
                        return (
                          <button
                            key={p.label}
                            type="button"
                            role="menuitem"
                            className="tool-popover-item"
                            onClick={() => {
                              const next = (value
                                ? value + (/\s$/.test(value) ? "" : " ")
                                : "") + p.send;
                              onChange(next.slice(0, MAX_CHARS));
                              setAddOpen(false);
                              textareaRef.current?.focus();
                            }}
                          >
                            <span className={`tool-popover-icon tone-${p.tone}`}>
                              <Icon />
                            </span>
                            <span className="tool-popover-text">
                              <span className="t-label">{p.label}</span>
                              <span className="t-sub">{p.send}</span>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
                <div className="tool-popover" ref={toolsRef}>
                  <button
                    type="button"
                    className={`tool-btn ${toolsOpen ? "open" : ""}`}
                    onClick={() => {
                      setAddOpen(false);
                      setToolsOpen((v) => !v);
                    }}
                    aria-haspopup="menu"
                    aria-expanded={toolsOpen}
                  >
                    <SlidersHorizontal /> Tools
                  </button>
                  {toolsOpen && (
                    <div className="tool-popover-menu wide" role="menu">
                      <div className="tool-popover-head">
                        <span>What your Persona can see</span>
                        <Link
                          href="/dashboard/settings/accounts"
                          className="tool-popover-manage"
                          onClick={() => setToolsOpen(false)}
                        >
                          Manage <ArrowUpRight size={12} strokeWidth={1.7} />
                        </Link>
                      </div>
                      {[
                        { label: "LinkedIn", desc: "Posts and profile", Icon: LinkedinIcon },
                        { label: "Your brief", desc: "A doc in your Drive", Icon: FileText },
                        { label: "Calendar", desc: "Free / busy times", Icon: Calendar },
                        { label: "Telegram", desc: "Chat from your phone", Icon: Send },
                      ].map((c) => (
                        <div key={c.label} className="tool-popover-row" role="menuitem">
                          <span className="tool-popover-icon tone-ink">
                            <c.Icon />
                          </span>
                          <span className="tool-popover-text">
                            <span className="t-label">{c.label}</span>
                            <span className="t-sub">{c.desc}</span>
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <button
                type="button"
                className={`mic-btn ${recording ? "recording" : ""}`}
                onClick={toggleMic}
                disabled={disabled}
                aria-label={recording ? "Stop recording" : "Start voice input"}
                aria-pressed={recording}
              >
                {recording ? <MicOff /> : <Mic />}
              </button>
            </div>
          </div>
        </div>

        <div className="disclaimer">
          {voiceError
            ? voiceError
            : recording
              ? "Listening… click the mic again to stop."
              : "Your Persona may make mistakes — double-check anything important."}
        </div>
      </div>
    </div>
  );
}
