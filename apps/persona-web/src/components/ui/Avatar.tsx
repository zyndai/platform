"use client";

import { useEffect, useState, type HTMLAttributes } from "react";

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
  const [broken, setBroken] = useState(false);

  useEffect(() => {
    setBroken(false);
  }, [src]);

  const classes = [
    "avatar",
    `avatar-${size}`,
    variant === "accent" ? "avatar-accent" : "",
    variant === "ink" ? "avatar-ink" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const showImage = !!src && !broken;

  return (
    <span className={classes} {...rest}>
      {showImage ? (
        <img
          src={src as string}
          alt={alt ?? name ?? ""}
          referrerPolicy="no-referrer"
          onError={() => setBroken(true)}
        />
      ) : (
        initial(name)
      )}
    </span>
  );
}
