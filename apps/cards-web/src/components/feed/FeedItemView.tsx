import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { KIND_LABEL, relativeTime, safeHref, type FeedItem } from "@/lib/feed";
import { hostnameOf, kindLabel, safeAskUrl } from "@/lib/asks";
import { PersonAvatar } from "@/components/discover/person-avatar";
import "./feed.css";

const PLATFORM_NAME = { linkedin: "LinkedIn", x: "X" } as const;

function Body({ item, preview }: { item: FeedItem; preview: boolean }) {
  switch (item.kind) {
    case "ask": {
      const href = safeAskUrl(item.content.url);
      return (
        <>
          <p className="fd-ask-kind">
            <span className="fd-chip">{kindLabel(item.content.kind)}</span>
          </p>
          <p className="fd-text is-ask">{item.content.text}</p>
          {href &&
            (preview ? (
              // The preview is not a place to leave from: same look, no link.
              <span className="fd-preview-link">
                {hostnameOf(href)} <ArrowUpRight size={13} aria-hidden="true" />
              </span>
            ) : (
              <a className="fd-ask-link" href={href} target="_blank" rel="noopener noreferrer nofollow ugc">
                {hostnameOf(href)} <ArrowUpRight size={13} aria-hidden="true" />
              </a>
            ))}
        </>
      );
    }
    case "working_on":
      return <p className="fd-text">{item.content.text}</p>;
    case "exploring": {
      const href = safeHref(item.content.url);
      return (
        <>
          <p className="fd-text">
            {href ? (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {item.content.title} <ArrowUpRight size={13} aria-hidden="true" />
              </a>
            ) : item.content.title}
          </p>
          {item.content.note && <p className="fd-note">{item.content.note}</p>}
        </>
      );
    }
    case "joined":
      return (
        <p className="fd-text">
          {item.author.name} joined Zynd
          {item.content.headline ? `: ${item.content.headline}` : ""}
          {item.content.can_help_with.length > 0 && (
            <span className="fd-note"> Can help with {item.content.can_help_with.join(", ")}.</span>
          )}
        </p>
      );
    case "github": {
      const href = safeHref(item.content.url);
      const what =
        item.content.type === "release" ? "Released" : item.content.type === "pull_request" ? "Merged a pull request in" : "Created";
      return (
        <p className="fd-text">
          {what} <strong>{item.content.repo}</strong>
          {item.content.title && <>: {item.content.title}</>}{" "}
          {href && (
            <a href={href} target="_blank" rel="noopener noreferrer">
              View on GitHub <ArrowUpRight size={13} aria-hidden="true" />
            </a>
          )}
        </p>
      );
    }
    case "post": {
      const href = safeHref(item.content.url);
      return (
        <>
          <p className="fd-text is-quote">{item.content.preview}</p>
          {href && (
            <a className="fd-out" href={href} target="_blank" rel="noopener noreferrer">
              Read the original on {PLATFORM_NAME[item.content.platform] ?? "the web"} <ArrowUpRight size={13} aria-hidden="true" />
            </a>
          )}
        </>
      );
    }
  }
}

/**
 * One feed item: the author, what happened, and why you are seeing it. The feed and the ask composer's
 * preview both render this, so a post looks in the composer exactly as it will in the feed. `footer`
 * carries what only the feed has (the reply button and its composer); a `preview` has no links out.
 */
export function FeedItemView({
  item,
  nowMs,
  preview = false,
  footer,
}: {
  item: FeedItem;
  nowMs: number;
  preview?: boolean;
  footer?: ReactNode;
}) {
  const who = item.author;
  return (
    <article className="fd-item" aria-labelledby={`fd-who-${item.id}`}>
      <div className="fd-item-head">
        <PersonAvatar name={who.name} src={who.avatar_url ?? undefined} size={44} />
        <div className="fd-who">
          {preview ? (
            <span id={`fd-who-${item.id}`} className="fd-name">{who.name}</span>
          ) : (
            <Link id={`fd-who-${item.id}`} className="fd-name" href={`/p/${encodeURIComponent(who.handle)}`}>
              {who.name}
            </Link>
          )}
          {(who.headline || who.location) && (
            <span className="fd-sub">{[who.headline, who.location].filter(Boolean).join(" · ")}</span>
          )}
        </div>
        <div className="fd-meta">
          <span className={`fd-kind is-${item.kind}`}>{KIND_LABEL[item.kind]}</span>
          <time dateTime={item.at}>{relativeTime(item.at, nowMs)}</time>
        </div>
      </div>
      <div className="fd-body"><Body item={item} preview={preview} /></div>
      {item.reason && <p className="fd-reason">{item.reason}</p>}
      {footer}
    </article>
  );
}
