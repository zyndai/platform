"use client";

import { useState } from "react";
import { initialsOf } from "@/lib/identity";

/** A person's photo, or their initials when there is no photo or it fails to load. */
export function PersonAvatar({ name, src, size = 56 }: { name: string; src?: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  const style = { width: size, height: size, borderRadius: Math.round(size * 0.3) };

  if (src && !failed) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt=""
        width={size}
        height={size}
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
        className="dc-avatar"
        style={style}
      />
    );
  }
  return (
    <span className="dc-avatar-fallback" style={style} aria-hidden="true">
      {initialsOf(name)}
    </span>
  );
}
