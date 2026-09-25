"use client";

import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";

// useLayoutEffect would warn during SSR; it never runs there anyway.
const useIsoLayoutEffect = typeof window !== "undefined" ? useLayoutEffect : useEffect;

/**
 * Wraps the page body in the scroll-veil effect: any descendant with a
 * `.zd-slide` class fades/slides in the first time it scrolls into view,
 * riding up over the sticky identity row pinned behind it. Runs from a
 * layout effect so server-rendered markup stays plain (no unveiled first
 * paint) and crawlers / no-JS readers see the full content either way.
 */
export function DossierShell({ children, className }: { children: ReactNode; className?: string }) {
  const shellRef = useRef<HTMLElement>(null);

  useIsoLayoutEffect(() => {
    const shell = shellRef.current;
    if (!shell || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const rows = Array.from(shell.querySelectorAll<HTMLElement>(".zd-slide"));
    rows.forEach((el) => el.classList.add("zd-veil"));

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.setAttribute("data-on", "1");
          io.unobserve(entry.target);
        }
      },
      { rootMargin: "0px 0px -18% 0px", threshold: 0.04 },
    );
    rows.forEach((el) => io.observe(el));

    return () => io.disconnect();
  }, []);

  return (
    <main ref={shellRef} className={className}>
      {children}
    </main>
  );
}
