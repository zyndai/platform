"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Check, Clock3, Send } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import {
  FEED_FILTERS,
  KIND_LABEL,
  MAX_REPLY_LENGTH,
  actionFor,
  fetchFeed,
  relativeTime,
  replyFor,
  replyToFeedItem,
  safeHref,
  type FeedConnection,
  type FeedFilter,
  type FeedItem,
  type FeedPage,
} from "@/lib/feed";
import { PersonAvatar } from "@/components/discover/person-avatar";

/** A fresh access token (the session renews itself), falling back to the one the page rendered with. */
async function currentToken(fallback: string): Promise<string> {
  try {
    const { data: { session } } = await createClient().auth.getSession();
    return session?.access_token || fallback;
  } catch {
    return fallback;
  }
}

const PLATFORM_NAME = { linkedin: "LinkedIn", x: "X" } as const;

/**
 * The action feed. Every item ends in one real action: a message to the author if you are connected,
 * a connection request carrying your message if you are not. One composer is open at a time, and the
 * connection state is kept per author here (not one status call per item), so replying to one
 * item updates every other item from the same person.
 */
export function FeedClient({
  initial,
  filter,
  token,
  nowMs,
}: {
  initial: FeedPage;
  filter: FeedFilter;
  token: string;
  nowMs: number;
}) {
  const [items, setItems] = useState(initial.items);
  const [cursor, setCursor] = useState(initial.next_cursor);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [connections, setConnections] = useState<Record<string, FeedConnection>>({});
  const [openId, setOpenId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState<Record<string, string>>({});
  const { has_card: hasCard, handle: myHandle } = initial.viewer;

  const connectionFor = (item: FeedItem): FeedConnection | null =>
    connections[item.author.handle.toLowerCase()] ?? item.connection;

  async function loadMore() {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    setLoadError("");
    try {
      const next = await fetchFeed(await currentToken(token), { filter, cursor });
      setItems((current) => {
        const known = new Set(current.map((i) => i.id));
        return [...current, ...next.items.filter((i) => !known.has(i.id))];
      });
      setCursor(next.next_cursor);
    } catch (failure) {
      setLoadError(failure instanceof Error ? failure.message : "Could not load more");
    } finally {
      setLoadingMore(false);
    }
  }

  function open(item: FeedItem) {
    setOpenId(item.id);
    setMessage(replyFor(item).prefill);
    setError("");
  }

  function close(item: FeedItem) {
    setOpenId(null);
    setError("");
    requestAnimationFrame(() => document.getElementById(`fd-reply-${item.id}`)?.focus());
  }

  async function send(item: FeedItem) {
    const text = message.trim();
    if (!text) {
      setError("Write a message first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      // One call: the server picks a message or a connection request from the real connection state.
      const result = await replyToFeedItem(await currentToken(token), item.id, text, crypto.randomUUID());
      const { id, status, incoming } = result.connection;
      setConnections((current) => ({ ...current, [item.author.handle.toLowerCase()]: { id, status, incoming } }));
      setSent((current) => ({ ...current, [item.id]: result.channel === "dm" ? `/network?c=${id}` : "/network" }));
      setOpenId(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not send. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  function actions(item: FeedItem) {
    const link = sent[item.id];
    if (link) {
      return (
        <span className="fd-status" role="status">
          <Check size={14} aria-hidden="true" /> Sent · <Link href={link}>View in Network</Link>
        </span>
      );
    }
    const action = actionFor(hasCard, connectionFor(item));
    switch (action.kind) {
      case "create-card":
        return <Link className="fd-button is-ghost" href="/create">Create your card to reply</Link>;
      case "requested":
        return (
          <button type="button" className="fd-button is-ghost" disabled>
            <Clock3 size={14} aria-hidden="true" /> Requested
          </button>
        );
      case "respond":
        return (
          <Link className="fd-button is-ghost" href={`/network?c=${action.connectionId}`}>
            {item.author.name.split(/\s+/)[0]} wants to connect · Respond
          </Link>
        );
      case "reply":
        return (
          <button
            id={`fd-reply-${item.id}`}
            type="button"
            className="fd-button"
            aria-expanded={openId === item.id}
            aria-controls={`fd-composer-${item.id}`}
            onClick={() => (openId === item.id ? close(item) : open(item))}
          >
            {replyFor(item).label}
          </button>
        );
    }
  }

  function composer(item: FeedItem) {
    const via = actionFor(hasCard, connectionFor(item));
    const dm = via.kind === "reply" && via.via === "dm";
    return (
      <form
        id={`fd-composer-${item.id}`}
        className="fd-composer"
        onSubmit={(event) => { event.preventDefault(); void send(item); }}
        onKeyDown={(event) => { if (event.key === "Escape") close(item); }}
      >
        <label className="fd-label" htmlFor={`fd-text-${item.id}`}>
          {dm ? `Message ${item.author.name}` : `Your note to ${item.author.name}`}
        </label>
        <textarea
          id={`fd-text-${item.id}`}
          autoFocus
          rows={3}
          maxLength={MAX_REPLY_LENGTH}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
        />
        <p className="fd-hint">
          {dm
            ? "You're connected, so this goes straight to their messages."
            : "This goes with your connection request. You can message each other once they accept."}
        </p>
        <div className="fd-composer-actions">
          <button type="submit" className="fd-button" disabled={busy}>
            <Send size={14} aria-hidden="true" /> {busy ? "Sending…" : dm ? "Send message" : "Send request"}
          </button>
          <button type="button" className="fd-button is-ghost" onClick={() => close(item)}>Cancel</button>
        </div>
        {error && <p className="fd-error" role="alert">{error}</p>}
      </form>
    );
  }

  function body(item: FeedItem) {
    switch (item.kind) {
      case "ask":
        return <p className="fd-text is-ask">{item.content.text}</p>;
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

  return (
    <div className="fd-page">
      <header className="fd-head">
        <h1>Feed</h1>
        <p>What people on Zynd are working on and asking for. Every item is a way to start a conversation.</p>
      </header>

      <nav className="fd-tabs" aria-label="Feed filter">
        {FEED_FILTERS.map((f) => (
          <Link
            key={f.id}
            href={f.id === "all" ? "/feed" : `/feed?filter=${f.id}`}
            className="fd-tab"
            aria-current={f.id === filter ? "page" : undefined}
          >
            {f.label}
          </Link>
        ))}
      </nav>

      {!hasCard && (
        <p className="fd-banner">
          You don&apos;t have a card yet. <Link href="/create">Create your card</Link> to reply to anyone here.
        </p>
      )}

      {items.length === 0 ? (
        <section className="fd-panel fd-empty">
          {filter === "asks" ? (
            <>
              <h2>No asks right now</h2>
              <p>
                When someone asks for help it shows up here for a week.{" "}
                <Link href={myHandle ? `/p/${encodeURIComponent(myHandle)}/edit` : "/create"}>
                  {myHandle ? "Post one from your card" : "Create your card to post one"}
                </Link>
              </p>
            </>
          ) : filter === "network" ? (
            <>
              <h2>Nothing from people you know yet</h2>
              <p>
                Updates from your connections appear here. <Link href="/directory">Find people to connect with</Link>
              </p>
            </>
          ) : (
            <>
              <h2>Nothing here yet</h2>
              <p>
                Updates, asks and launches from other cards appear here as they happen.{" "}
                <Link href="/directory">Browse the directory</Link>
              </p>
            </>
          )}
        </section>
      ) : (
        <ul className="fd-list">
          {items.map((item, index) => {
            const who = item.author;
            const when = relativeTime(item.at, nowMs);
            const startsEarlier = item.earlier && !items[index - 1]?.earlier;
            return (
              <li key={item.id}>
                {startsEarlier && (
                  <div className="fd-divider" role="separator" aria-label="Earlier items">
                    <span>Earlier</span>
                  </div>
                )}
                <article className="fd-item" aria-labelledby={`fd-who-${item.id}`}>
                  <div className="fd-item-head">
                    <PersonAvatar name={who.name} src={who.avatar_url ?? undefined} size={44} />
                    <div className="fd-who">
                      <Link id={`fd-who-${item.id}`} className="fd-name" href={`/p/${encodeURIComponent(who.handle)}`}>
                        {who.name}
                      </Link>
                      {(who.headline || who.location) && (
                        <span className="fd-sub">{[who.headline, who.location].filter(Boolean).join(" · ")}</span>
                      )}
                    </div>
                    <div className="fd-meta">
                      <span className={`fd-kind is-${item.kind}`}>{KIND_LABEL[item.kind]}</span>
                      <time dateTime={item.at}>{when}</time>
                    </div>
                  </div>
                  <div className="fd-body">{body(item)}</div>
                  {item.reason && <p className="fd-reason">{item.reason}</p>}
                  <div className="fd-actions">{actions(item)}</div>
                  {openId === item.id && composer(item)}
                </article>
              </li>
            );
          })}
        </ul>
      )}

      {cursor && (
        <div className="fd-more">
          <button type="button" className="fd-button is-ghost" disabled={loadingMore} onClick={() => void loadMore()}>
            {loadingMore ? "Loading…" : "Load more"}
          </button>
          {loadError && <p className="fd-error" role="alert">{loadError}</p>}
        </div>
      )}
    </div>
  );
}
