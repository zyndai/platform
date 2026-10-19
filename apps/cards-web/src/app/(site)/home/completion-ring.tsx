"use client";

import { useEffect, useRef, useState } from "react";

export function CompletionRing({ score }: { score: number }) {
  const target = Math.min(100, Math.max(0, score));
  const [progress, setProgress] = useState(0);
  const current = useRef(0);

  useEffect(() => {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const from = current.current;
    let started: number | undefined;
    let frame = 0;

    const animate = (now: number) => {
      started ??= now;
      const elapsed = motion.matches ? 1 : Math.min(1, (now - started) / 1400);
      const next = elapsed === 1 ? target : from + (target - from) * (1 - Math.pow(1 - elapsed, 3));
      current.current = next;
      setProgress(next);
      if (elapsed < 1) frame = requestAnimationFrame(animate);
    };

    frame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame);
  }, [target]);

  return (
    <div
      className="oh-ring"
      role="img"
      aria-label={`Card completeness ${target}%`}
      style={{ background: `conic-gradient(var(--oh-accent) ${progress}%, #ffffff80 0)` }}
    >
      <span aria-hidden="true">{Math.round(progress)}<small>%</small></span>
    </div>
  );
}
