"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

/** About text clamped to a few lines (set in edition.css) with a "Read more"
 *  toggle that only appears when the text is actually cut off. */
export function EditionAboutText({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const ref = useRef<HTMLParagraphElement>(null);
  const id = useId();

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    // Measured while clamped; the clamp changes with the viewport, so re-check on resize.
    const observer = new ResizeObserver(() => {
      if (!el.classList.contains("is-clamped")) return;
      setOverflows(el.scrollHeight > el.clientHeight + 1);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <>
      <p ref={ref} id={id} className={`ed-about-text${expanded ? "" : " is-clamped"}`}>{text}</p>
      {(overflows || expanded) && (
        <button type="button" className="ed-read-more" aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Show less" : "Read more"}
          <ChevronDown size={15} aria-hidden style={{ transform: expanded ? "rotate(180deg)" : undefined }} />
        </button>
      )}
    </>
  );
}
