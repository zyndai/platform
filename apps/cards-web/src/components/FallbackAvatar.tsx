"use client";

import { useState } from "react";

interface FallbackAvatarProps {
  src: string;
  alt: string;
  initials: string;
  size?: number;
  radius?: number | string;
  border?: string;
  background?: string;
}

/** An <img> that swaps to a neutral initials block when the image fails to load. */
export function FallbackAvatar({
  src,
  alt,
  initials,
  size = 44,
  radius = 12,
  border = "1px solid #e2e8f0",
  background = "#f8fafc",
}: FallbackAvatarProps) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <span
        role="img"
        aria-label={alt}
        style={{
          width: size,
          height: size,
          borderRadius: radius,
          border,
          background,
          flexShrink: 0,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: Math.max(12, Math.round(size * 0.36)),
          fontWeight: 800,
          color: "#64748b",
        }}
      >
        {initials}
      </span>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={alt}
      width={size}
      height={size}
      onError={() => setFailed(true)}
      style={{
        width: size,
        height: size,
        borderRadius: radius,
        objectFit: "cover",
        border,
        flexShrink: 0,
        background,
        display: "block",
      }}
    />
  );
}