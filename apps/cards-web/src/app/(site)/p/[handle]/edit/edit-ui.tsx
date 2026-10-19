"use client";

import { useState, type ReactNode } from "react";
import { Check, X, Zap } from "lucide-react";

export type ToastType = "ok" | "err" | "info";
export type ShowToast = (msg: string, type?: ToastType) => void;

/** One titled card. `id` doubles as the deep-link anchor (/edit#skills). */
export function Card({ id, title, hint, action, children }: {
  id?: string; title: string; hint?: ReactNode; action?: ReactNode; children?: ReactNode;
}) {
  const titleId = id ? `${id}-title` : undefined;
  return (
    <section className="pe-card" id={id} aria-labelledby={titleId}>
      <div className="pe-card-head">
        <div>
          <h2 className="pe-card-title" id={titleId}>{title}</h2>
          {hint && <p className="pe-card-hint">{hint}</p>}
        </div>
        {action && <div className="pe-card-action">{action}</div>}
      </div>
      {children}
    </section>
  );
}

export function Field({ label, htmlFor, className, children }: {
  label: string; htmlFor?: string; className?: string; children: ReactNode;
}) {
  return (
    <div className={className}>
      <label className="pe-label" htmlFor={htmlFor}>{label}</label>
      {children}
    </div>
  );
}

export function TagInput({ id, tags, onChange, placeholder }: {
  id?: string; tags: string[]; onChange: (t: string[]) => void; placeholder?: string;
}) {
  const [input, setInput] = useState("");
  function commit() {
    const v = input.trim();
    if (v && !tags.includes(v)) onChange([...tags, v]);
    setInput("");
  }
  return (
    <div className="pe-tags">
      {tags.map((t) => (
        <span key={t} className="pe-chip">
          <span className="truncate">{t}</span>
          <button type="button" onClick={() => onChange(tags.filter((x) => x !== t))} aria-label={`Remove ${t}`}>
            <X size={12} />
          </button>
        </span>
      ))}
      <input
        id={id}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); commit(); } }}
        onBlur={commit}
        placeholder={tags.length ? "Add more" : placeholder ?? "Type, then Enter"}
      />
    </div>
  );
}

export function Toast({ msg, type }: { msg: string; type: ToastType }) {
  return (
    <div className={`pe-toast ${type}`} aria-live="polite">
      {type === "ok" ? <Check size={14} /> : type === "err" ? <X size={14} /> : <Zap size={14} />}
      <span>{msg}</span>
    </div>
  );
}
