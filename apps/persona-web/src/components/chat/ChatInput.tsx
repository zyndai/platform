"use client";

import {
  forwardRef,
  memo,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
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
  Square,
  ArrowUpRight,
} from "lucide-react";
import { QUICK_PROMPTS } from "./quickPrompts";
import { getSupabase } from "@/lib/supabase";
import { suggestSlashCommands, type SlashCommandDef } from "@/lib/services-commands";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function LinkedinIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" {...props}>
      <path d="M20.45 20.45h-3.55v-5.57c0-1.33-.03-3.04-1.85-3.04-1.86 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zm1.78 13.02H3.55V9h3.57v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z" />
    </svg>
  );
}

// Pick the best audio mime type the current browser will actually record in.
// Chrome/Edge ship `audio/webm;codecs=opus`, Safari does `audio/mp4`, and
// some platforms only do generic `audio/webm`. Groq's Whisper accepts all
// of these, so we just hand off whatever MediaRecorder produces — we only
// need this when we want to NAME the file extension for the upload.
function pickAudioMime(): { mime: string; ext: string } | null {
  if (typeof MediaRecorder === "undefined") return null;
  const candidates: Array<{ mime: string; ext: string }> = [
    { mime: "audio/webm;codecs=opus", ext: "webm" },
    { mime: "audio/webm",             ext: "webm" },
    { mime: "audio/mp4",              ext: "m4a" },
    { mime: "audio/mpeg",             ext: "mp3" },
  ];
  for (const c of candidates) {
    if (MediaRecorder.isTypeSupported(c.mime)) return c;
  }
  return null;
}

interface SuggestPill {
  label: string;
  send: string;
}

interface ChatInputProps {
  onSend: (text: string) => void;
  /** Called when the user interrupts a streaming reply (Stop button / Esc). */
  onStop?: () => void;
  /** True while an SSE response is open. Swaps the Send button for a Stop button
   *  and binds Escape to onStop. */
  streaming?: boolean;
  disabled?: boolean;
  pills?: SuggestPill[];
  placeholder?: string;
  variant?: "v1" | "v2";
}

/** Imperative handle so the parent can clear/focus the box without owning the
 *  draft text — keeping keystrokes off the parent's render path. */
export interface ChatInputHandle {
  clear: () => void;
  focus: () => void;
}

const MAX_CHARS = 3000;

const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(function ChatInput(
  {
    onSend,
    onStop,
    streaming = false,
    disabled = false,
    pills,
    placeholder = "Ask your agent anything…  Try /services <query>",
    variant = "v2",
  }: ChatInputProps,
  ref,
) {
  // The draft text lives HERE, not in the parent — typing must not re-render
  // ChatInterface (and the whole message thread) on every keystroke.
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const hasText = value.trim().length > 0;

  useImperativeHandle(
    ref,
    () => ({
      clear: () => setValue(""),
      focus: () => textareaRef.current?.focus(),
    }),
    [],
  );

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

  // Voice-to-text via MediaRecorder + Groq Whisper (server-side).
  //
  // Click mic → request mic, start recording. Click again → stop, POST the
  // audio blob to /api/transcribe, append the returned text to the input.
  // Much more reliable than the browser's SpeechRecognition API (which
  // routes through Google's servers, drops sessions on silence, and is
  // gated behind opaque restart quirks). The actual recognition runs on
  // Groq's Whisper-Large-v3-turbo — fast (~1s for a 30s clip) and free
  // for our volume.
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const mimeRef = useRef<{ mime: string; ext: string } | null>(null);
  // Keep a live `value` ref so the recorder's `onstop` closure appends to the
  // latest draft instead of a stale one captured when recording started.
  const valueRef = useRef(value);
  useEffect(() => { valueRef.current = value; }, [value]);

  const releaseStream = () => {
    const s = streamRef.current;
    if (!s) return;
    for (const t of s.getTracks()) {
      try { t.stop(); } catch { /* noop */ }
    }
    streamRef.current = null;
  };

  const stopRecording = useCallback(() => {
    const r = recorderRef.current;
    if (!r) return;
    try { r.stop(); } catch { /* state error, ignore */ }
    // onstop handler will release the stream + POST the audio.
  }, []);

  const startRecording = useCallback(async () => {
    if (recording || transcribing) return;
    const pick = pickAudioMime();
    if (!pick || typeof navigator === "undefined" || !navigator.mediaDevices) {
      setVoiceError("Voice input isn't supported in this browser.");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      if (/NotAllowed|denied/i.test(msg)) {
        setVoiceError("Mic permission was denied. Allow it in your browser settings.");
      } else {
        setVoiceError("Couldn't access the microphone.");
      }
      return;
    }
    streamRef.current = stream;
    mimeRef.current = pick;
    chunksRef.current = [];

    const rec = new MediaRecorder(stream, { mimeType: pick.mime });
    rec.ondataavailable = (e: BlobEvent) => {
      if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
    };
    rec.onstop = async () => {
      const audio = new Blob(chunksRef.current, { type: pick.mime });
      chunksRef.current = [];
      releaseStream();
      recorderRef.current = null;
      setRecording(false);

      if (audio.size < 1000) {
        // Nothing meaningful captured (under ~1KB ≈ silence or instant tap).
        return;
      }

      setTranscribing(true);
      try {
        const fd = new FormData();
        fd.append("file", audio, `voice.${pick.ext}`);
        const sb = getSupabase();
        const { data: { session } } = await sb.auth.getSession();
        const res = await fetch(`${API_URL}/api/transcribe/`, {
          method: "POST",
          headers: session?.access_token
            ? { Authorization: `Bearer ${session.access_token}` }
            : {},
          body: fd,
        });
        if (!res.ok) {
          const detail = await res.text().catch(() => "");
          throw new Error(detail || `Transcription failed (${res.status})`);
        }
        const data = await res.json();
        const text = ((data && data.text) || "").trim();
        if (!text) return;

        const base = valueRef.current;
        const sep = base && !/\s$/.test(base) ? " " : "";
        setValue((base + sep + text).slice(0, MAX_CHARS));
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Couldn't transcribe.";
        setVoiceError(
          msg.length > 120 ? "Couldn't transcribe — try again." : msg,
        );
      } finally {
        setTranscribing(false);
      }
    };
    rec.onerror = () => {
      setVoiceError("Recording failed — try again.");
      releaseStream();
      recorderRef.current = null;
      setRecording(false);
    };

    recorderRef.current = rec;
    setVoiceError(null);
    setRecording(true);
    try {
      rec.start();
    } catch {
      setVoiceError("Couldn't start the recorder.");
      releaseStream();
      recorderRef.current = null;
      setRecording(false);
    }
  }, [recording, transcribing]);

  const toggleMic = useCallback(() => {
    if (disabled) return;
    if (recording) stopRecording();
    else void startRecording();
  }, [disabled, recording, startRecording, stopRecording]);

  // Cleanup on unmount: stop the recorder and release the mic stream so
  // the OS-level recording indicator goes away even if the user navigates
  // away mid-recording.
  useEffect(() => {
    return () => {
      const r = recorderRef.current;
      if (r && r.state !== "inactive") {
        try { r.stop(); } catch { /* noop */ }
      }
      releaseStream();
      recorderRef.current = null;
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
    setValue("");
  };

  // ── Slash-command autocomplete ────────────────────────────────────
  // When the input starts with `/` and the user is still typing the command
  // name (no space yet), show a small popover above the input listing the
  // matching commands. Arrow keys + Enter/Tab to pick; Esc to dismiss.
  const slashSuggestions: SlashCommandDef[] = suggestSlashCommands(value) || [];
  const slashOpen = slashSuggestions.length > 0;
  const [slashIndex, setSlashIndex] = useState(0);
  useEffect(() => {
    // Reset the highlight whenever the suggestion list changes (e.g., the
    // user typed another letter and the list shrank — keep the highlight
    // valid).
    if (slashIndex >= slashSuggestions.length) setSlashIndex(0);
  }, [slashSuggestions.length, slashIndex]);

  const pickSlashCommand = useCallback(
    (cmd: SlashCommandDef) => {
      setValue(cmd.insertText);
      // Move the caret to end of inserted text so the user can immediately
      // type the argument. requestAnimationFrame gives React a tick to
      // apply the value update before we move the caret.
      requestAnimationFrame(() => {
        const el = textareaRef.current;
        if (!el) return;
        el.focus();
        el.setSelectionRange(cmd.insertText.length, cmd.insertText.length);
      });
    },
    [],
  );

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
            onChange={(e) => setValue(e.target.value.slice(0, MAX_CHARS))}
            onKeyDown={(e) => {
              if (e.key === "Escape" && streaming && onStop) {
                e.preventDefault();
                onStop();
                return;
              }
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder={placeholder}
            // Streaming should NOT disable the textarea — the user can
            // still type their next prompt while the current one streams,
            // and Esc only works if the field is focusable.
            disabled={disabled && !streaming}
            aria-label="Chat with your Persona"
          />
          {streaming && onStop ? (
            <button
              type="button"
              className="send-btn stop-btn"
              onClick={onStop}
              aria-label="Stop generating"
              title="Stop generating (Esc)"
            >
              <Square />
            </button>
          ) : (
            <button
              type="button"
              className="send-btn"
              onClick={handleSend}
              disabled={!hasText || disabled}
              aria-label="Send"
            >
              <ArrowUp />
            </button>
          )}
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

        {slashOpen && (
          <ul
            className="slash-picker"
            role="listbox"
            aria-label="Slash commands"
          >
            {slashSuggestions.map((cmd, i) => (
              <li
                key={cmd.name}
                role="option"
                aria-selected={i === slashIndex}
                className={`slash-picker-row ${i === slashIndex ? "is-active" : ""}`}
                onMouseEnter={() => setSlashIndex(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pickSlashCommand(cmd);
                }}
              >
                <span className="slash-picker-name">/{cmd.name}</span>
                {cmd.args && (
                  <span className="slash-picker-args">{cmd.args}</span>
                )}
                <span className="slash-picker-desc">{cmd.description}</span>
              </li>
            ))}
          </ul>
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
                  setValue(next);
                }}
                onKeyDown={(e) => {
                  if (slashOpen) {
                    if (e.key === "ArrowDown") {
                      e.preventDefault();
                      setSlashIndex((i) => (i + 1) % slashSuggestions.length);
                      return;
                    }
                    if (e.key === "ArrowUp") {
                      e.preventDefault();
                      setSlashIndex(
                        (i) =>
                          (i - 1 + slashSuggestions.length) % slashSuggestions.length,
                      );
                      return;
                    }
                    if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
                      e.preventDefault();
                      pickSlashCommand(slashSuggestions[slashIndex]);
                      return;
                    }
                    if (e.key === "Escape") {
                      e.preventDefault();
                      // Clear the leading slash so the popover hides without
                      // having to track a separate dismiss flag.
                      setValue("");
                      return;
                    }
                  }
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
                              setValue(next.slice(0, MAX_CHARS));
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
                        { label: "Your brief", desc: "Your long-form context", Icon: FileText },
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
                className={`mic-btn ${recording ? "recording" : ""} ${transcribing ? "transcribing" : ""}`}
                onClick={toggleMic}
                disabled={disabled || transcribing}
                aria-label={recording ? "Stop recording" : transcribing ? "Transcribing…" : "Start voice input"}
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
            : transcribing
              ? "Transcribing…"
              : recording
                ? "Listening… click the mic again to stop."
                : null}
        </div>
      </div>
    </div>
  );
});

export default memo(ChatInput);
