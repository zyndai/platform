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
  Code2,
  X,
} from "lucide-react";
import { QUICK_PROMPTS } from "./quickPrompts";
import { getSupabase } from "@/lib/supabase";
import { apiGet } from "@/lib/api";
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
  /** Opens the "Publish HTML" dialog — lets the user paste a full page
   *  without the chat message's character cap. Only rendered in v2. */
  onPublishHtml?: () => void;
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
    onPublishHtml,
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
    let t = value.trim();
    if (!t || disabled) return;
    const pickedTitles = todoSuggestions
      .filter((s) => selectedTodoIds.has(s.id))
      .map((s) => s.title);
    for (const title of pickedTitles) {
      if (t.includes(title)) t = t.replace(title, `{{todo::${title}}}`);
    }
    setSelectedTodoIds(new Set());
    onSend(t);
    setValue("");
  };

  // ── "/todo" picker state — declared ahead of the slash-command block
  // below since it needs to know todoPickerOpen to decide whether the
  // generic "/" popover should still render. See the full comment further
  // down, next to the effects that drive this picker.
  const [todoPickerOpen, setTodoPickerOpen] = useState(false);
  const [todoSuggestions, setTodoSuggestions] = useState<
    { id: string; title: string; done: boolean }[]
  >([]);
  const [todoPickerLoading, setTodoPickerLoading] = useState(false);
  const [todoIndex, setTodoIndex] = useState(0);
  const [selectedTodoIds, setSelectedTodoIds] = useState<Set<string>>(new Set());
  const [todoInsert, setTodoInsert] = useState<{ prefix: string; suffix: string } | null>(null);

  // ── Slash-command autocomplete ────────────────────────────────────
  // When the input starts with `/` and the user is still typing the command
  // name (no space yet), show a small popover above the input listing the
  // matching commands. Arrow keys + Enter/Tab to pick; Esc to dismiss.
  const slashSuggestions: SlashCommandDef[] = suggestSlashCommands(value) || [];
  // Once the todo picker takes over (see below), it owns the popover UI.
  const slashOpen = slashSuggestions.length > 0 && !todoPickerOpen;
  const [slashIndex, setSlashIndex] = useState(0);
  useEffect(() => {
    // Reset the highlight whenever the suggestion list changes (e.g., the
    // user typed another letter and the list shrank — keep the highlight
    // valid).
    if (slashIndex >= slashSuggestions.length) setSlashIndex(0);
  }, [slashSuggestions.length, slashIndex]);

  const pickSlashCommand = useCallback(
    (cmd: SlashCommandDef) => {
      if (cmd.name === "todo") {
        setTodoInsert({ prefix: "", suffix: "" });
        setTodoPickerOpen(true);
        setSelectedTodoIds(new Set());
        setValue("");
        return;
      }
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

  // ── "/todo" picker — lists my open todos with a checkbox per row so I
  // can select several at once. Typing "/todo" ANYWHERE in the draft (not
  // just as the whole message) triggers it — same detection shape as the
  // "@" mention scan in the group composer: walk back from the caret to
  // the start of the current whitespace-delimited token and check it's
  // exactly "/todo". `todoInsert` remembers what came before/after that
  // token so the picker can splice the picked-items summary back into the
  // same spot instead of clobbering the rest of the message. Every toggle
  // re-renders the draft as "1. first title, 3. third title …" (numbered
  // by list position so it's clear which items were picked). Mirrors the
  // group chat's composer picker (webapp/src/app/dashboard/groups/[id]/page.tsx).
  const detectTodoTrigger = useCallback((text: string, caret: number) => {
    let i = caret - 1;
    while (i >= 0 && !/\s/.test(text[i])) i -= 1;
    const tokenStart = i + 1;
    if (text.slice(tokenStart, caret) !== "/todo") return null;
    return { prefix: text.slice(0, tokenStart), suffix: text.slice(caret) };
  }, []);

  useEffect(() => {
    if (!todoPickerOpen) return;
    let cancelled = false;
    setTodoPickerLoading(true);
    apiGet<{ todos: { id: string; title: string; done: boolean }[] }>("/api/todos/", {
      noCache: true,
    })
      .then((data) => {
        if (!cancelled) setTodoSuggestions(data.todos.filter((t) => !t.done));
      })
      .catch(() => {
        if (!cancelled) setTodoSuggestions([]);
      })
      .finally(() => {
        if (!cancelled) setTodoPickerLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [todoPickerOpen]);

  useEffect(() => {
    if (todoIndex >= todoSuggestions.length) setTodoIndex(0);
  }, [todoSuggestions.length, todoIndex]);

  // While the picker is open, the "/todo" spot IS the checked-items summary
  // — kept in sync live as boxes are (un)checked, with the rest of the
  // message (todoInsert.prefix/suffix) left untouched. Once closed
  // (Enter/Tab/Escape) this stops running, so the user is free to edit.
  useEffect(() => {
    if (!todoPickerOpen || !todoInsert) return;
    const parts = todoSuggestions
      .map((t, i) => ({ t, num: i + 1 }))
      .filter(({ t }) => selectedTodoIds.has(t.id))
      .map(({ t, num }) => `${num}. ${t.title}`);
    const summary = parts.length ? parts.join(", ") + " " : "";
    const nextValue = todoInsert.prefix + summary + todoInsert.suffix;
    setValue(nextValue);
    const caretPos = todoInsert.prefix.length + summary.length;
    requestAnimationFrame(() => {
      textareaRef.current?.setSelectionRange(caretPos, caretPos);
    });
  }, [selectedTodoIds, todoSuggestions, todoPickerOpen, todoInsert]);

  const toggleTodoSelection = useCallback((id: string) => {
    setSelectedTodoIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const closeTodoPicker = useCallback(
    (cancel: boolean) => {
      setTodoPickerOpen(false);
      if (cancel && todoInsert) {
        setSelectedTodoIds(new Set());
        setValue(todoInsert.prefix + todoInsert.suffix);
      }
      setTodoInsert(null);
      requestAnimationFrame(() => textareaRef.current?.focus());
    },
    [todoInsert],
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
        {todoPickerOpen && (
          <div className="todo-picker-popover">
            <button
              type="button"
              className="todo-picker-close"
              aria-label="Close todo picker"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => closeTodoPicker(false)}
            >
              <X size={13} strokeWidth={2} />
            </button>
          <ul className="slash-picker" role="listbox" aria-label="Your todos" aria-multiselectable="true">
            {todoPickerLoading ? (
              <li className="slash-picker-row" style={{ cursor: "default" }}>
                <span className="slash-picker-desc">Loading your todos…</span>
              </li>
            ) : todoSuggestions.length === 0 ? (
              <li className="slash-picker-row" style={{ cursor: "default" }}>
                <span className="slash-picker-desc">No open todos — add one on the Todos tab.</span>
              </li>
            ) : (
              todoSuggestions.map((t, i) => (
                <li
                  key={t.id}
                  role="option"
                  aria-selected={selectedTodoIds.has(t.id)}
                  className={`slash-picker-row todo-picker-row ${i === todoIndex ? "is-active" : ""}`}
                  onMouseEnter={() => setTodoIndex(i)}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    toggleTodoSelection(t.id);
                  }}
                >
                  <input
                    type="checkbox"
                    readOnly
                    checked={selectedTodoIds.has(t.id)}
                    className="todo-picker-checkbox"
                    tabIndex={-1}
                  />
                  <span className="slash-picker-desc">
                    {i + 1}. {t.title}
                  </span>
                </li>
              ))
            )}
          </ul>
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
                  const caret = e.target.selectionStart ?? next.length;
                  setValue(next);
                  if (!todoPickerOpen) {
                    const trigger = detectTodoTrigger(next, caret);
                    if (trigger) {
                      setTodoInsert(trigger);
                      setTodoPickerOpen(true);
                      setSelectedTodoIds(new Set());
                      setValue(trigger.prefix + trigger.suffix);
                    }
                  }
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
                  if (todoPickerOpen) {
                    if (e.key === "ArrowDown") {
                      e.preventDefault();
                      if (todoSuggestions.length > 0) {
                        setTodoIndex((i) => (i + 1) % todoSuggestions.length);
                      }
                      return;
                    }
                    if (e.key === "ArrowUp") {
                      e.preventDefault();
                      if (todoSuggestions.length > 0) {
                        setTodoIndex(
                          (i) => (i - 1 + todoSuggestions.length) % todoSuggestions.length,
                        );
                      }
                      return;
                    }
                    if (e.key === "Tab") {
                      e.preventDefault();
                      if (todoSuggestions[todoIndex]) toggleTodoSelection(todoSuggestions[todoIndex].id);
                      return;
                    }
                    if (e.key === "Enter") {
                      e.preventDefault();
                      closeTodoPicker(false);
                      return;
                    }
                    if (e.key === "Escape") {
                      e.preventDefault();
                      closeTodoPicker(true);
                      return;
                    }
                  }
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                onBlur={() => {
                  if (todoPickerOpen) closeTodoPicker(false);
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
                {onPublishHtml && (
                  <button
                    type="button"
                    className="tool-btn"
                    onClick={onPublishHtml}
                    title="Paste and publish a full HTML page — no character limit"
                  >
                    <Code2 /> Publish HTML
                  </button>
                )}
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
