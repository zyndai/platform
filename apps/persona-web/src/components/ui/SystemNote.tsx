import type { HTMLAttributes, ReactNode } from "react";

interface SystemNoteProps extends HTMLAttributes<HTMLDivElement> {
  parts?: ReactNode[];
}

/**
 * An inline system note in the chat thread — "Sent to Ravi's assistant · just now".
 * Pass either `children` (free-form) or `parts` (an array joined with mid-dots).
 */
export function SystemNote({
  parts,
  className = "",
  children,
  ...rest
}: SystemNoteProps) {
  return (
    <div className={`system-note ${className}`.trim()} {...rest}>
      {parts
        ? parts.map((part, i) => (
            <span key={i} style={{ display: "inline-flex", alignItems: "center" }}>
              {i > 0 && <span className="dot-sep" aria-hidden="true" />}
              <span>{part}</span>
            </span>
          ))
        : children}
    </div>
  );
}
