import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { endsIn, hostnameOf, kindLabel, safeAskUrl, type LiveAsk } from "@/lib/asks";

/**
 * "Your live ask", pinned at the top of the feed: what it says, who it reached, who offered, when it
 * ends. Edit opens the composer with it filled in; Manage goes to the close-out panel on /home.
 */
export function LiveAskCard({ ask, nowMs, onEdit }: { ask: LiveAsk; nowMs: number; onEdit: () => void }) {
  const href = safeAskUrl(ask.url);
  return (
    <section className="fd-item fd-live" aria-labelledby="fd-live-title">
      <div className="fd-live-head">
        <h2 id="fd-live-title" className="fd-live-title">Your live ask</h2>
        <span className="fd-chip">{kindLabel(ask.kind)}</span>
      </div>
      <p className="fd-text is-ask">{ask.text}</p>
      {href && (
        <a className="fd-ask-link" href={href} target="_blank" rel="noopener noreferrer nofollow ugc">
          {hostnameOf(href)} <ArrowUpRight size={13} aria-hidden="true" />
        </a>
      )}
      <ul className="fd-live-stats">
        {ask.routed > 0 && <li>Sent to {ask.routed} {ask.routed === 1 ? "person" : "people"}</li>}
        <li>{ask.offer_count > 0 ? `${ask.offer_count} offered help` : "No offers yet"}</li>
        <li>{endsIn(ask.expires_at, nowMs)}</li>
      </ul>
      <div className="fd-actions">
        <button type="button" className="fd-button" onClick={onEdit}>Edit</button>
        <Link className="fd-button is-ghost" href="/home#ask-closeout">Manage</Link>
      </div>
    </section>
  );
}
