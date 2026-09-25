import type { HTMLAttributes } from "react";

interface TagProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "muted" | "outline";
}

export function Tag({
  variant = "default",
  className = "",
  children,
  ...rest
}: TagProps) {
  const classes = [
    "tag",
    variant === "muted" ? "tag-muted" : "",
    variant === "outline" ? "tag-outline" : "",
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
