import { MapPin } from "lucide-react";

import { PersonAvatar } from "@/components/discover/person-avatar";
import { imgProxyUrl } from "@/lib/avatar";
import type { AgentProfileCard } from "@/lib/cards";
import type { LiveIdentity } from "./model";

const SKILLS_SHOWN = 6;
const POSTS_SHOWN = 2;

/**
 * The card as it will be published, filling in as the build goes: first from
 * whatever each source has revealed, then from the written draft with the
 * person's answers and edits applied.
 */
export function LiveCard({ live, card, building, handle }: {
  live: LiveIdentity;
  /** The draft as it would publish, or null until the first build finishes. */
  card: AgentProfileCard | null;
  building: boolean;
  handle: string;
}) {
  const name = card?.identity.name || live.name;
  const headline = card?.identity.headline || live.headline;
  const location = card?.identity.location || live.location;
  const photo = imgProxyUrl(card?.identity.avatar_url || live.avatar);
  const summary = card?.summary || live.bio;
  const skills = card?.skills.slice(0, SKILLS_SHOWN).map((s) => s.name) ?? [];
  const facts = card ? [] : live.facts;
  const posts = (card ? card.writing_samples.map((w) => w.excerpt) : live.posts).slice(0, POSTS_SHOWN);
  const helps = card?.can_help_with.slice(0, 4) ?? [];
  const empty = !name && !headline && !summary;

  return (
    <section className="cr-live" aria-label="Live preview of your card" data-testid="live-card">
      <div className="cr-live-top">
        <span className="dc-label">Live preview</span>
        <span className="cr-state" data-tone={building ? undefined : card ? "ok" : undefined}>
          {building ? <><span className="cr-spinner" aria-hidden="true" /> Filling in</> : card ? "Draft" : "Waiting"}
        </span>
      </div>

      {empty ? (
        <div className="cr-live-who" aria-hidden="true">
          <div className="cr-skel" style={{ width: 56, height: 56, borderRadius: 17, flexShrink: 0 }} />
          <div style={{ display: "grid", gap: 8, flex: 1 }}>
            <div className="cr-skel" style={{ height: 18, width: "70%" }} />
            <div className="cr-skel" style={{ height: 13, width: "50%" }} />
          </div>
        </div>
      ) : (
        <div className="cr-live-who cr-in">
          <PersonAvatar name={name || "?"} src={photo} size={56} />
          <div style={{ minWidth: 0 }}>
            <div className="cr-live-name">{name || "Your name"}</div>
            {location && <div className="cr-live-meta"><MapPin size={13} aria-hidden="true" /> {location}</div>}
          </div>
        </div>
      )}

      {headline && <div className="cr-live-text cr-in" style={{ color: "var(--dc-ink)", fontWeight: 600 }}>{headline}</div>}
      {summary && <div className="cr-live-text is-clamp cr-in">{summary}</div>}

      {(skills.length > 0 || facts.length > 0) && (
        <div className="dc-chips cr-in">
          {skills.map((s) => <span key={s} className="dc-chip">{s}</span>)}
          {facts.map((f) => <span key={f} className="dc-chip dc-chip-plain">{f}</span>)}
        </div>
      )}

      {helps.length > 0 && (
        <div style={{ display: "grid", gap: 7 }} className="cr-in">
          <span className="dc-label">Can help with</span>
          <div className="dc-chips">{helps.map((h) => <span key={h} className="dc-chip dc-chip-plain">{h}</span>)}</div>
        </div>
      )}

      {posts.length > 0 && (
        <div className="cr-live-posts cr-in">
          <span className="dc-label">Recent posts</span>
          {posts.map((p) => <div key={p} className="cr-quote">{p}</div>)}
        </div>
      )}

      <span className="cr-url">zynd.ai/p/{handle || "you"}</span>
    </section>
  );
}
