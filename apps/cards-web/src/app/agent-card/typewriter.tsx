"use client";

import { useEffect, useRef, useState } from "react";

type Phase = "idle" | "typing" | "done";

/**
 * Types `text` out one character at a time, starting when the element first
 * scrolls into view.
 *
 * The full string is always rendered in an invisible sizer underneath, which
 * does two jobs: it reserves the final line box so nothing reflows mid-type,
 * and it keeps the complete sentence in the server-rendered HTML for crawlers
 * (the visible layer starts empty, so without it the copy would be invisible
 * to anything that doesn't run the animation).
 *
 * Driven off requestAnimationFrame against elapsed time rather than one
 * setTimeout per character — a per-character timer chain drifts badly once
 * render cost is added, which made the line take ~2x its nominal duration.
 */
export function Typewriter({
  text,
  durationMs = 2400,
  startDelay = 300,
  className = "",
}: {
  text: string;
  durationMs?: number;
  startDelay?: number;
  className?: string;
}) {
  const [count, setCount] = useState(0);
  const [phase, setPhase] = useState<Phase>("idle");
  const hostRef = useRef<HTMLSpanElement>(null);

  // Start on first scroll into view.
  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;

    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const noObserver = typeof IntersectionObserver === "undefined";

    // Reader asked for reduced motion, or we can't detect visibility: show the
    // finished line. Deferred a frame so we never setState in the effect body.
    if (reduce || noObserver) {
      const raf = requestAnimationFrame(() => {
        if (reduce) {
          setCount(text.length);
          setPhase("done");
        } else {
          setPhase("typing");
        }
      });
      return () => cancelAnimationFrame(raf);
    }

    const io = new IntersectionObserver(
      entries => {
        if (entries.some(e => e.isIntersecting)) {
          setPhase("typing");
          io.disconnect();
        }
      },
      { threshold: 0.35 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [text]);

  useEffect(() => {
    if (phase !== "typing") return;
    const msPerChar = durationMs / Math.max(1, text.length);
    const begin = performance.now();
    let raf = requestAnimationFrame(function tick(now) {
      const elapsed = now - begin - startDelay;
      const n = elapsed <= 0 ? 0 : Math.min(text.length, Math.ceil(elapsed / msPerChar));
      setCount(n);
      if (n < text.length) raf = requestAnimationFrame(tick);
      else setPhase("done");
    });
    return () => cancelAnimationFrame(raf);
  }, [phase, text, durationMs, startDelay]);

  return (
    <span ref={hostRef} className={`relative block ${className}`}>
      {/* Sizer: reserves the full line box and carries the text for crawlers. */}
      <span className="invisible" aria-hidden="true">{text}</span>
      <span className="absolute inset-0">
        {text.slice(0, count)}
        <span
          className={`tw-caret${phase === "done" ? " tw-caret-idle" : ""}`}
          aria-hidden="true"
        />
      </span>
    </span>
  );
}
