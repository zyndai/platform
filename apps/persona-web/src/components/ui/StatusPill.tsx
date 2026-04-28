import type { HTMLAttributes } from "react";

interface StatusPillProps extends HTMLAttributes<HTMLSpanElement> {
  pulsing?: boolean;
}

/**
 * Small badge with an optional pulsing accent dot.
 * Used for "Aria is online" type indicators.
 */
export function StatusPill({
  pulsing = true,
  className = "",
  children,
  ...rest
}: StatusPillProps) {
  return (
    <span className={`status-pill ${className}`.trim()} {...rest}>
      {pulsing && <span className="status-dot" aria-hidden="true" />}
      <span>{children}</span>
    </span>
  );
}
