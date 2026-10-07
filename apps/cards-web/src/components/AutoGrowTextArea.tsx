"use client";

import { useEffect, useLayoutEffect, useRef } from "react";

/**
 * A textarea that grows with its content instead of scrolling.
 *
 * Height follows scrollHeight on every value change and on container resizes
 * (e.g. the review column going from 2-up to 1-up on mobile). Still fully
 * editable — it's a plain textarea, just never shows an inner scrollbar.
 */
export function AutoGrowTextArea({
  value,
  onChange,
  minRows = 3,
  maxHeight,
  placeholder,
  className,
  style,
  onKeyDown,
  id,
  ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  minRows?: number;
  maxHeight?: number;
  placeholder?: string;
  className?: string;
  style?: React.CSSProperties;
  onKeyDown?: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  id?: string;
  ariaLabel?: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  const grow = () => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.overflowY = "hidden";
    let next = el.scrollHeight;
    if (maxHeight && next > maxHeight) {
      next = maxHeight;
      el.style.overflowY = "auto";
    }
    el.style.height = `${next}px`;
  };

  useLayoutEffect(grow, [value, minRows, maxHeight]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => grow());
    ro.observe(el);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <textarea
      ref={ref}
      id={id}
      aria-label={ariaLabel}
      rows={minRows}
      value={value}
      placeholder={placeholder}
      className={className}
      style={style}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={onKeyDown}
    />
  );
}