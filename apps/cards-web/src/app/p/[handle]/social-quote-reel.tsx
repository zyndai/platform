"use client";

import { useEffect, useRef, useState } from "react";

interface SocialQuoteReelProps {
  quotes: string[];
  intervalMs?: number;
}

/**
 * One social post at a time. Marquee stacking painted two italic layers
 * on top of each other and made the copy unreadable.
 */
export function SocialQuoteReel({ quotes, intervalMs = 6000 }: SocialQuoteReelProps) {
  const items = quotes.map((q) => q.trim()).filter(Boolean);
  const [index, setIndex] = useState(0);
  const pausedRef = useRef(false);
  const count = items.length;

  useEffect(() => {
    if (count < 2) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const id = window.setInterval(() => {
      if (!pausedRef.current) setIndex((n) => (n + 1) % count);
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [count, intervalMs]);

  if (count === 0) return null;

  const safeIndex = index % count;
  const text = items[safeIndex];

  return (
    <div
      className="pf-quote-reel"
      onMouseEnter={() => { pausedRef.current = true; }}
      onMouseLeave={() => { pausedRef.current = false; }}
      onFocusCapture={() => { pausedRef.current = true; }}
      onBlurCapture={() => { pausedRef.current = false; }}
    >
      <p className="pf-quote-text">{text}</p>
      {count > 1 && (
        <div className="pf-mono pf-quote-count" aria-hidden>
          {safeIndex + 1}/{count}
        </div>
      )}
    </div>
  );
}
