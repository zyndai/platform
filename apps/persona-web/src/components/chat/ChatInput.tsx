"use client";

import { useEffect, useRef } from "react";
import { ArrowUp } from "lucide-react";

interface SuggestPill {
  label: string;
  send: string;
}

interface ChatInputProps {
  value: string;
  onChange: (next: string) => void;
  onSend: (text: string) => void;
  disabled?: boolean;
  /** Optional pills shown above the input (typically only on a fresh thread). */
  pills?: SuggestPill[];
  placeholder?: string;
}

export default function ChatInput({
  value,
  onChange,
  onSend,
  disabled = false,
  pills,
  placeholder = "Tell Aria what's on your mind…",
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const hasText = value.trim().length > 0;

  // Auto-grow up to 5 rows. Cheap height-juggle pattern.
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const lineHeight = 22; // matches Geist 14.5 / 1.55
    const max = lineHeight * 5 + 8;
    ta.style.height = Math.min(ta.scrollHeight, max) + "px";
    ta.style.overflowY = ta.scrollHeight > max ? "auto" : "hidden";
  }, [value]);

  const handleSend = () => {
    const t = value.trim();
    if (!t || disabled) return;
    onSend(t);
  };

  return (
    <div
      style={{
        padding: "16px 48px 28px",
        maxWidth: 800,
        margin: "0 auto",
        width: "100%",
      }}
    >
      {pills && pills.length > 0 && (
        <div className="suggest-pills">
          {pills.map((p, i) => (
            <button
              key={i}
              type="button"
              onClick={() => {
                if (disabled) return;
                onSend(p.send);
              }}
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
          aria-label="Chat with Aria"
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
