import type { HTMLAttributes } from "react";

interface ThinkingDotProps extends HTMLAttributes<HTMLSpanElement> {
  size?: "md" | "lg";
  label?: string;
}

/**
 * One slow-pulsing accent dot. The brief's alternative to a three-dot
 * typing indicator. Appears where Aria's next message will land.
 */
export function ThinkingDot({
  size = "md",
  label = "Aria is thinking",
  className = "",
  ...rest
}: ThinkingDotProps) {
  const classes = [
    "thinking-dot",
    size === "lg" ? "thinking-dot-lg" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <span
      className={classes}
      role="status"
      aria-label={label}
      {...rest}
    />
  );
}
