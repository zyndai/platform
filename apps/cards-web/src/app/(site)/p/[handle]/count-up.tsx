"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

// useLayoutEffect would warn during SSR; it never runs there anyway.
const useIsoLayoutEffect = typeof window !== "undefined" ? useLayoutEffect : useEffect;

interface Parsed {
  prefix: string;
  value: number;
  suffix: string;
  decimals: number;
  grouped: boolean;
}

/**
 * Splits a display figure into the part worth animating and the part that must
 * survive verbatim: "500+" → 500 with a "+", "14.2k" → 14.2 with a "k",
 * "1,420" → 1420 rendered with thousands separators. Anything without a number
 * in it (e.g. the "—" placeholder) returns null and is left alone.
 */
function parseFigure(raw: string): Parsed | null {
  const m = raw.match(/^(\D*?)(\d[\d,]*(?:\.\d+)?)(.*)$/);
  if (!m) return null;
  const [, prefix, num, suffix] = m;
  const plain = num.replace(/,/g, "");
  const dot = plain.indexOf(".");
  return {
    prefix,
    value: Number.parseFloat(plain),
    suffix,
    decimals: dot === -1 ? 0 : plain.length - dot - 1,
    grouped: num.includes(","),
  };
}

function render(n: number, p: Parsed): string {
  const body = p.grouped
    ? n.toLocaleString("en-US", { minimumFractionDigits: p.decimals, maximumFractionDigits: p.decimals })
    : n.toFixed(p.decimals);
  return `${p.prefix}${body}${p.suffix}`;
}

interface CountUpProps {
  value: number | string;
  /** ms the roll-up takes once it starts. */
  duration?: number;
  /** ms to hold at zero first, for staggering a row of figures. */
  delay?: number;
}

/**
 * Rolls a stat from zero up to its real value the first time it scrolls into
 * view. The final value is what renders on the server, so crawlers and no-JS
 * readers see the real number; the animation only replaces it after hydration.
 */
export function CountUp({ value, duration = 1100, delay = 0 }: CountUpProps) {
  const final = String(value);
  const [text, setText] = useState(final);
  const ref = useRef<HTMLSpanElement>(null);

  useIsoLayoutEffect(() => {
    const el = ref.current;
    const parsed = parseFigure(final);
    if (!el || !parsed) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let raf = 0;
    let started = false;

    const start = () => {
      if (started) return;
      started = true;
      setText(render(0, parsed));
      const t0 = performance.now() + delay;
      const step = (now: number) => {
        const t = Math.min(1, Math.max(0, (now - t0) / duration));
        if (t >= 1) {
          setText(final); // land on the exact source string, not a rounded one
          return;
        }
        // easeOutExpo — fast out of the gate, long settle
        setText(render(parsed.value * (1 - Math.pow(2, -10 * t)), parsed));
        raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    };

    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          io.disconnect();
          start();
        }
      },
      { threshold: 0.4 },
    );
    io.observe(el);

    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [final, duration, delay]);

  return <span ref={ref}>{text}</span>;
}
