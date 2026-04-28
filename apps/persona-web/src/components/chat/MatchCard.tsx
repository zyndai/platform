"use client";

import { Avatar, Button } from "@/components/ui";
import type { PersonaHit } from "./types";

interface MatchCardProps {
  hit: PersonaHit;
  busy?: boolean;
  onSayHi: () => void;
  /** Optional headline override (e.g., LinkedIn headline). Falls back to
   *  the first sentence of `hit.description`. */
  headline?: string;
  /** Short excerpt of a recent post — rendered as an italic Fraunces
   *  pull-quote with a 2px accent left-border per the S6 spec. */
  pullQuote?: string;
  /** Aria's reason for surfacing this match. Falls back to the rest of
   *  `hit.description` after the first sentence. */
  reason?: string;
}

/**
 * Match card used at S6 (onboarding three-matches screen) and S9 (inline
 * in the home chat thread). Anatomy: avatar + name + headline + optional
 * pull-quote + Aria's reasoning + Say-hi button.
 */
export default function MatchCard({
  hit,
  busy = false,
  onSayHi,
  headline,
  pullQuote,
  reason,
}: MatchCardProps) {
  const desc = (hit.description || "").trim();
  const dotIdx = desc.indexOf(". ");
  const fallbackHeadline = dotIdx > 0 ? desc.slice(0, dotIdx) : desc;
  const fallbackReason   = dotIdx > 0 ? desc.slice(dotIdx + 2).trim() : "";
  const finalHeadline = headline || fallbackHeadline;
  const finalReason   = reason   || fallbackReason;

  return (
    <div className="match-card">
      <Avatar size="md" name={hit.name || "?"} variant="accent" />
      <div className="match-info">
        <div className="match-name">{hit.name || "Someone"}</div>
        {finalHeadline && <div className="match-headline">{finalHeadline}</div>}
        {pullQuote && (
          <blockquote className="match-pullquote italic-pull">
            “{pullQuote}”
          </blockquote>
        )}
        {finalReason && <div className="match-reason body">{finalReason}</div>}
      </div>
      <div className="match-action">
        <Button onClick={onSayHi} disabled={busy} rightIcon={<span aria-hidden>→</span>}>
          {busy ? "Opening…" : "Say hi"}
        </Button>
        <span className="caption match-caption">sent to their assistant first</span>
      </div>
    </div>
  );
}
