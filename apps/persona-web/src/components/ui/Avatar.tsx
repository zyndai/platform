import type { HTMLAttributes } from "react";

type Size = "xl" | "lg" | "md" | "sm" | "xs";

interface AvatarProps extends HTMLAttributes<HTMLSpanElement> {
  size?: Size;
  src?: string | null;
  name?: string | null;
  variant?: "default" | "accent" | "ink";
  alt?: string;
}

function initial(name: string | null | undefined): string {
  if (!name) return "?";
  const trimmed = name.trim();
  return trimmed[0]?.toUpperCase() ?? "?";
}

export function Avatar({
  size = "md",
  src,
  name,
  variant = "default",
  alt,
  className = "",
  ...rest
}: AvatarProps) {
  const classes = [
    "avatar",
    `avatar-${size}`,
    variant === "accent" ? "avatar-accent" : "",
    variant === "ink" ? "avatar-ink" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <span className={classes} {...rest}>
      {src ? <img src={src} alt={alt ?? name ?? ""} /> : initial(name)}
    </span>
  );
}
