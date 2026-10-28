import type { ReactNode } from "react";
import { Diamond, Hammer, MessagesSquare, UserRound, Users, Zap } from "lucide-react";
import { EDITION_FONT_VARS } from "@/components/editions/fonts";

type SignalKey = "love_talking_about" | "working_on" | "connect_with";

interface Signal {
  key: SignalKey;
  label: string;
  items: string[];
  /** Unchanged for lib/stale-signals STALE_DAYS: chips dim, with a hint. */
  stale?: boolean;
  /** Under the hint, e.g. the owner's confirm prompt. */
  staleFooter?: ReactNode;
}

const TONE: Record<SignalKey, { tone: string; head: ReactNode; chip: ReactNode }> = {
  love_talking_about: { tone: "mint", head: <MessagesSquare size={16} aria-hidden />, chip: <Diamond size={13} aria-hidden /> },
  working_on: { tone: "peach", head: <Hammer size={16} aria-hidden />, chip: <Zap size={13} aria-hidden /> },
  connect_with: { tone: "lavender", head: <Users size={16} aria-hidden />, chip: <UserRound size={13} aria-hidden /> },
};

// Enough to read as a set without the card turning into a wall of chips.
const MAX_CHIPS = 8;

/** The three signal cards (Love talking about / Working on / Connect with) for
 *  a card on the Mumbai Builder Week edition, in place of the classic stack.
 *  About lives in the identity card above, so these size to their own chips. */
export function EditionSignals({ signals }: { signals: Signal[] }) {
  if (signals.length === 0) return null;
  return (
    <div className={`pf-span-12 ed ed-signals ${EDITION_FONT_VARS}`} data-count={signals.length}>
      {signals.map((signal) => {
        const { tone, head, chip } = TONE[signal.key];
        const shown = signal.items.slice(0, MAX_CHIPS);
        const more = signal.items.length - shown.length;
        return (
          <section
            key={signal.key}
            id={signal.stale ? "working-on" : undefined}
            className={`ed-card ed-signal ed-tone-${tone}${signal.stale ? " is-stale" : ""}`}
            aria-label={signal.label}
          >
            <div className="ed-card-head">
              {head}
              <span className="ed-card-label">{signal.label}</span>
              <span className="ed-count" aria-label={`${signal.items.length} items`}>{signal.items.length}</span>
            </div>
            <ul className="ed-signal-chips">
              {shown.map((item) => (
                <li key={item} className="ed-signal-chip">{chip}<span>{item}</span></li>
              ))}
              {more > 0 && <li className="ed-signal-chip ed-signal-more">+{more} more</li>}
            </ul>
            {signal.stale && (
              <>
                <p className="ed-signal-stale">Not updated in 3+ months</p>
                {signal.staleFooter}
              </>
            )}
          </section>
        );
      })}
    </div>
  );
}
