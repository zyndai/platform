import type { HTMLAttributes } from "react";

interface ChipProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "muted";
}

export function Chip({
  variant = "default",
  className = "",
  children,
  ...rest
}: ChipProps) {
  const classes = [
    "chip",
    variant === "muted" ? "chip-muted" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <span className={classes} {...rest}>
      {children}
    </span>
  );
}
