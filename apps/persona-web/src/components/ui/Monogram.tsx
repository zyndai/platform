import type { HTMLAttributes } from "react";

type Size = "lg" | "md" | "sm" | "xs";

interface MonogramProps extends HTMLAttributes<HTMLSpanElement> {
  size?: Size;
  glyph?: string;
}

/**
 * Aria's monogram mark — placeholder until a real SVG is commissioned.
 * Per the brief, a single Fraunces glyph in the accent color.
 */
export function Monogram({
  size = "md",
  glyph = "Z",
  className = "",
  ...rest
}: MonogramProps) {
  return (
    <span
      aria-hidden="true"
      className={`monogram monogram-${size} ${className}`.trim()}
      {...rest}
    >
      {glyph}
    </span>
  );
}
