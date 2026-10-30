"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Check, Clock3, Send } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import {
  FEED_FILTERS,
  MAX_REPLY_LENGTH,
  actionFor,
  fetchFeed,
  replyFor,
  replyToFeedItem,
  type FeedConnection,
  type FeedFilter,
  type FeedItem,
  type FeedPage,
} from "@/lib/feed";
import { ASK_KINDS, type AskKind, type LiveAsk } from "@/lib/asks";
import { FeedItemView } from "@/components/feed/FeedItemView";
import { ReportControl } from "@/components/feed/ReportControl";
import { AskComposer } from "@/components/asks/AskComposer";
import { AskFab } from "@/components/asks/AskFab";
import { LiveAskCard } from "@/components/asks/LiveAskCard";

/** A fresh access token (the session renews itself), falling back to the one the page rendered with. */
async function currentToken(fallback: string): Promise<string> {
  try {
    const { data: { session } } = await createClient().auth.getSession();
    return session?.access_token || fallback;
  } catch {
    return fallback;
  }
}

/** How long a "your ask is live" note stays on screen. */
const TOAST_MS = 6000;

/**
 * The action feed. Every item ends in one real action: a message to the author if you are connected,
 * a connection request carrying your message if you are not. One composer is open at a time, and the
 * connection state is kept per author here (not one status call per item), so replying to one
 * item updates every other item from the same person.
 */
export function FeedClient({
  initial,
  filter,
  kind,
  live: initialLive,
  token,
  nowMs,
}: {
  initial: FeedPage;
  filter: FeedFilter;
  /** The asks tab's type filter; null for all types. */
  kind: AskKind | null;
  /** The viewer's own live ask, if they have one. */
  live: LiveAsk | null;
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
  const [live, setLive] = useState(initialLive);
  const [composerMode, setComposer] = useState<null | "new" | "edit">(null);
  const [toast, setToast] = useState("");
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (toastTimer.current) clearTimeout(toastTimer.current); }, []);

  function say(message: string) {
    setToast(message);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), TOAST_MS);
  }

  const connectionFor = (item: FeedItem): FeedConnection | null =>
    connections[item.author.handle.toLowerCase()] ?? item.connection;

  async function loadMore() {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    setLoadError("");
    try {
      const next = await fetchFeed(await currentToken(token), { filter, kind, cursor });
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

  const viewer = initial.viewer;

  return (
    <div className="fd-page">
      <header className="fd-head">
        <h1>Feed</h1>
        <p>What people on Zynd are working on and asking for. Every item is a way to start a conversation.</p>
      </header>

      {live && (
        <LiveAskCard ask={live} nowMs={nowMs} onEdit={() => setComposer("edit")} />
      )}

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

      {filter === "asks" && (
        <nav className="fd-kinds" aria-label="Type of ask">
          <Link className="fd-chip" href="/feed?filter=asks" aria-current={kind === null ? "true" : undefined}>All</Link>
          {ASK_KINDS.map((k) => (
            <Link
              key={k.id}
              className="fd-chip"
              href={`/feed?filter=asks&kind=${k.id}`}
              aria-current={kind === k.id ? "true" : undefined}
            >
              {k.label}
            </Link>
          ))}
        </nav>
      )}

      {!hasCard && (
        <p className="fd-banner">
          You don&apos;t have a card yet. <Link href="/create">Create your card</Link> to reply to anyone here.
        </p>
      )}

      {items.length === 0 ? (
        <section className="fd-panel fd-empty">
          {filter === "asks" ? (
            <>
              <h2>{kind ? "No asks of this type right now" : "No asks right now"}</h2>
              <p>
                When someone asks for help it shows up here for a week.{" "}
                {hasCard ? (
                  <button type="button" className="fd-linkbutton fd-inline" onClick={() => setComposer("new")}>Post an ask</button>
                ) : (
                  <Link href="/create">Create your card to post one</Link>
                )}
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
            const startsEarlier = item.earlier && !items[index - 1]?.earlier;
            return (
              <li key={item.id}>
                {startsEarlier && (
                  <div className="fd-divider" role="separator" aria-label="Earlier items">
                    <span>Earlier</span>
                  </div>
                )}
                <FeedItemView
                  item={item}
                  nowMs={nowMs}
                  footer={
                    <>
                      <div className="fd-actions">
                        {actions(item)}
                        {item.kind === "ask" && <ReportControl token={token} handle={item.author.handle} name={item.author.name} />}
                      </div>
                      {openId === item.id && composer(item)}
                    </>
                  }
                />
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

      {toast && <p className="fd-toast" role="status">{toast}</p>}
      <AskFab onClick={() => setComposer("new")} />
      <AskComposer
        open={composerMode !== null}
        edit={composerMode === "edit"}
        onClose={() => setComposer(null)}
        getToken={() => currentToken(token)}
        hasCard={hasCard}
        author={{
          handle: myHandle ?? "",
          name: viewer.name ?? "",
          headline: viewer.headline ?? "",
          avatar_url: viewer.avatar_url ?? null,
          location: viewer.location ?? "",
        }}
        live={live}
        onPosted={(ask) => {
          setLive(ask);
          setComposer(null);
          say("Your ask is live for 7 days.");
        }}
        onTakenDown={() => {
          setLive(null);
          setComposer(null);
          say("Your ask is down.");
        }}
      />
    </div>
  );
}
