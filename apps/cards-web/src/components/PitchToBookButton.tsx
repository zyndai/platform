"use client";

import type { CSSProperties, ReactNode } from "react";

/** Event ProfileChatWidget listens for to open on its pitch step. */
export const OPEN_PITCH_EVENT = "zynd:open-pitch";

/** The booking card's CTA when the owner asks for a pitch first: there is no link to show yet. */
export function PitchToBookButton({ className, style, children }: { className?: string; style?: CSSProperties; children: ReactNode }) {
  return (
    <button type="button" className={className} style={style} onClick={() => window.dispatchEvent(new Event(OPEN_PITCH_EVENT))}>
      {children}
    </button>
  );
}
