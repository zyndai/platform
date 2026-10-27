"use client";

import { AutoGrowTextArea } from "@/components/AutoGrowTextArea";

/** A line of the card you edit where it is drawn: it reads as text until you hover or focus it. */
export function InlineText({ value, onChange, label, placeholder, className = "" }: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  placeholder?: string;
  className?: string;
}) {
  return (
    <input
      className={`cr-inline ${className}`} value={value} aria-label={label} placeholder={placeholder}
      autoComplete="off" onChange={(e) => onChange(e.target.value)}
    />
  );
}

/** The same for a paragraph: it grows with what is written. */
export function InlineArea({ value, onChange, label, placeholder, minRows = 3 }: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  placeholder?: string;
  minRows?: number;
}) {
  return (
    <AutoGrowTextArea
      value={value} onChange={onChange} minRows={minRows} placeholder={placeholder}
      className="cr-inline cr-inline-area" ariaLabel={label}
    />
  );
}
