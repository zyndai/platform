"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { X } from "lucide-react";
import {
  ASK_KINDS,
  ASK_LIFETIME_DAYS,
  ASK_TEXT_MAX,
  AskError,
  endsIn,
  kindLabel,
  liveFromPosted,
  postAsk,
  takeDownAsk,
  validateAskUrl,
  type AskKind,
  type LiveAsk,
} from "@/lib/asks";
import type { FeedItem } from "@/lib/feed";
import { FeedItemView } from "@/components/feed/FeedItemView";
import { EDITION_FONT_VARS } from "@/components/editions/fonts";
import "./ask-composer.css";

/** Whoever is posting, as the preview shows them (their own card). */
export interface ComposerAuthor {
  handle: string;
  name: string;
  headline: string;
  avatar_url: string | null;
  location: string;
}

/** Where focus goes when the composer closes and the thing that opened it is gone. */
export const ASK_FAB_ID = "ask-post-fab";

const FOCUSABLE = 'a[href], button:not(:disabled), input:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

interface Props {
  open: boolean;
  onClose: () => void;
  /** A fresh access token (the session renews itself). */
  getToken: () => Promise<string>;
  hasCard: boolean;
  author: ComposerAuthor;
  /** The owner's live ask, if any: shown at the top, and replaced by what is posted. */
  live: LiveAsk | null;
  /** Open with the live ask filled in, to change it. */
  edit?: boolean;
  onPosted: (ask: LiveAsk) => void;
  onTakenDown: () => void;
}

/**
 * The composer for an ask: pick what you are looking for, say it in 280 characters, add a link if you
 * like, see it as the feed will show it, post. A modal dialog on a desktop, a bottom sheet on a phone.
 * One live ask per card: posting replaces it (the page says so), and "Take it down" removes it. Used on
 * the feed (the Post button) and the edit page, so there is one way to post everywhere.
 */
export function AskComposer(props: Props) {
  if (!props.open || typeof document === "undefined") return null;
  return createPortal(<Dialog {...props} />, document.body);
}

function Dialog({ onClose, getToken, hasCard, author, live, edit = false, onPosted, onTakenDown }: Props) {
  const titleId = useId();
  const kindName = useId();
  const textId = useId();
  const urlId = useId();
  const urlErrorId = useId();
  const countId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const urlRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<AskKind | null>(edit && live ? (live.kind ?? "other") : null);
  const [text, setText] = useState(edit && live ? live.text : "");
  const [url, setUrl] = useState(edit && live?.url ? live.url : "");
  const [urlError, setUrlError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmDown, setConfirmDown] = useState(false);
  const [nowMs] = useState(() => Date.now());

  // The dialog behaviour: focus in, Tab kept inside, Esc closes, the page behind does not scroll, and
  // focus goes back to what opened it. The handlers read the latest props through refs.
  const closeRef = useRef(onClose);
  const busyRef = useRef(busy);
  useEffect(() => {
    closeRef.current = onClose;
    busyRef.current = busy;
  });
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const root = dialogRef.current;
    (root?.querySelector<HTMLElement>("input[type=radio]:checked") ?? root?.querySelector<HTMLElement>("input[type=radio], a[href]") ?? root)?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (!busyRef.current) closeRef.current();
        return;
      }
      if (event.key !== "Tab" || !root) return;
      const controls = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE));
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (!first || !last) return;
      if (!root.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      document.body.style.overflow = overflow;
      (opener?.isConnected ? opener : document.getElementById(ASK_FAB_ID))?.focus();
    };
  }, []);

  const placeholder = ASK_KINDS.find((k) => k.id === kind)?.placeholder ?? "Pick what you're looking for, then say it in a sentence or two";
  const checked = validateAskUrl(url);
  const trimmed = text.trim();
  const preview: FeedItem = {
    id: "preview",
    kind: "ask",
    at: new Date(nowMs).toISOString(),
    earlier: false,
    reason: "",
    author: { ...author, name: author.name || "You", claimed: true },
    content: { text: trimmed || "Your ask will show up here.", kind: kind ?? "other", url: checked.ok ? checked.url : null },
    connection: null,
  };

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!kind || !trimmed || busy) return;
    if (!checked.ok) {
      setUrlError(checked.error);
      urlRef.current?.focus();
      return;
    }
    setBusy(true);
    setError("");
    let posted: LiveAsk;
    try {
      const result = await postAsk(await getToken(), { kind, text: trimmed, url: checked.url });
      posted = liveFromPosted(result.beacon);
    } catch (failure) {
      setError(failure instanceof AskError || failure instanceof Error ? failure.message : "Could not post your ask. Please try again.");
      setBusy(false);
      return;
    }
    onPosted(posted);
  }

  async function takeDown() {
    setBusy(true);
    setError("");
    try {
      await takeDownAsk(await getToken());
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not take your ask down. Please try again.");
      setBusy(false);
      return;
    }
    onTakenDown();
  }

  return (
    <div
      className={`ac-backdrop fd-scope ${EDITION_FONT_VARS}`}
      onMouseDown={(event) => {
        if (event.target !== event.currentTarget || busy) return;
        event.preventDefault();         // or the browser blurs the button focus is about to return to
        onClose();
      }}
    >
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className="ac-dialog">
        <header className="ac-head">
          <h2 id={titleId}>{edit ? "Edit your ask" : "Post an ask"}</h2>
          <button type="button" className="ac-close" aria-label="Close" onClick={onClose} disabled={busy}>
            <X size={18} aria-hidden="true" />
          </button>
        </header>

        {!hasCard ? (
          <div className="ac-body">
            <p className="ac-lead">Create your card to post</p>
            <p className="ac-hint">An ask goes out from your card, so people can see who is asking and write back.</p>
            <div className="ac-row">
              <Link className="fd-button" href="/create">Create your card</Link>
              <button type="button" className="fd-button is-ghost" onClick={onClose}>Not now</button>
            </div>
          </div>
        ) : (
          <form className="ac-form" onSubmit={(event) => void submit(event)} noValidate>
            <div className="ac-body">
              {live && (
                <section className="ac-live" aria-label="Your current ask">
                  <p className="ac-live-top">
                    <span className="fd-chip">{kindLabel(live.kind)}</span>
                    <span className="ac-hint">{endsIn(live.expires_at, nowMs)}</span>
                  </p>
                  <p className="ac-live-text">{live.text}</p>
                  <p className="ac-warn">Posting this replaces your current ask.</p>
                  {confirmDown ? (
                    <div className="ac-row" role="group" aria-label="Take your ask down">
                      <span className="ac-hint">Take it down for good?</span>
                      <button type="button" className="fd-button" disabled={busy} onClick={() => void takeDown()} autoFocus>
                        {busy ? "Taking down…" : "Yes, take it down"}
                      </button>
                      <button type="button" className="fd-button is-ghost" disabled={busy} onClick={() => setConfirmDown(false)}>Keep it</button>
                    </div>
                  ) : (
                    <button type="button" className="fd-linkbutton" disabled={busy} onClick={() => setConfirmDown(true)}>Take it down</button>
                  )}
                </section>
              )}

              <fieldset className="ac-kinds">
                <legend className="ac-label">What are you looking for?</legend>
                <div className="ac-chips">
                  {ASK_KINDS.map((k) => (
                    <label key={k.id} className="ac-kind">
                      <input type="radio" name={kindName} value={k.id} checked={kind === k.id} onChange={() => setKind(k.id)} />
                      <span>{k.label}</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <div className="ac-field">
                <label className="ac-label" htmlFor={textId}>Your ask</label>
                <textarea
                  id={textId}
                  rows={4}
                  maxLength={ASK_TEXT_MAX}
                  value={text}
                  placeholder={placeholder}
                  aria-describedby={countId}
                  onChange={(event) => setText(event.target.value)}
                />
                <p id={countId} className="ac-count">{text.length}/{ASK_TEXT_MAX}</p>
              </div>

              <div className="ac-field">
                <label className="ac-label" htmlFor={urlId}>Link <span className="ac-hint">(optional)</span></label>
                <input
                  ref={urlRef}
                  id={urlId}
                  type="text"
                  inputMode="url"
                  autoComplete="off"
                  placeholder="https://"
                  value={url}
                  aria-invalid={urlError ? true : undefined}
                  aria-describedby={urlError ? urlErrorId : undefined}
                  onChange={(event) => { setUrl(event.target.value); setUrlError(""); }}
                  onBlur={() => setUrlError(checked.ok ? "" : checked.error)}
                />
                {urlError && <p id={urlErrorId} className="fd-error">{urlError}</p>}
              </div>

              <div className="ac-preview">
                <p className="ac-label" id={`${countId}-preview`}>How it will look</p>
                <div role="group" aria-labelledby={`${countId}-preview`}>
                  <FeedItemView item={preview} nowMs={nowMs} preview />
                </div>
              </div>
            </div>

            <footer className="ac-foot">
              {error && <p className="fd-error" role="alert">{error}</p>}
              <div className="ac-foot-row">
                <p className="ac-hint">Visible for {ASK_LIFETIME_DAYS} days · sent to people who match</p>
                <button type="submit" className="fd-button" disabled={!kind || !trimmed || busy}>
                  {busy && !confirmDown ? "Posting…" : "Post"}
                </button>
              </div>
            </footer>
          </form>
        )}
      </div>
    </div>
  );
}
