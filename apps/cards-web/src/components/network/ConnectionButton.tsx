"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Check, Clock3, MessageCircle, UserPlus } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import {
  cardsNetworkRequest,
  connectionRequestNotice,
  connectionState,
  fetchConnectionStatus,
  type CardConnection,
  type ConnectionSummary,
} from "@/lib/cards-network";

type View =
  | { kind: "loading" }
  | { kind: "signed-out" }
  | { kind: "hidden" }
  | { kind: "ready"; token: string; connection: ConnectionSummary | null; canConnect: boolean; reason: string | null };

const POPOVER_WIDTH = 264;

/**
 * The Connect / Message pill in a Card's purple hero (styles: .pf-connect* in the profile page).
 *
 * It asks the Cards API where the signed-in viewer stands with this Card and shows the one action
 * that can work: Connect (with an optional note), Requested, Accept, or Message. Your own Card
 * renders nothing. If the status call fails the pill falls back to Connect, and the request itself
 * then reports the truth (for example "already connected").
 *
 * `variant="edition"` restyles it for the white identity card of an edition (accent button instead
 * of a white pill on the purple hero).
 */
export function ConnectionButton({ handle, name, variant }: { handle: string; name?: string; variant?: "edition" }) {
  const [view, setView] = useState<View>({ kind: "loading" });
  const [open, setOpen] = useState(false);
  const [popover, setPopover] = useState({ left: 0, width: POPOVER_WIDTH });
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const anchorRef = useRef<HTMLSpanElement>(null);
  const pillRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      let token = "";
      try {
        const { data: { session } } = await createClient().auth.getSession();
        token = session?.access_token ?? "";
      } catch {
        token = "";
      }
      if (controller.signal.aborted) return;
      if (!token) {
        setView({ kind: "signed-out" });
        return;
      }
      try {
        const status = await fetchConnectionStatus(token, handle, controller.signal);
        if (controller.signal.aborted) return;
        setView(status.self
          ? { kind: "hidden" }
          : { kind: "ready", token, connection: status.connection, canConnect: status.can_connect, reason: status.reason });
      } catch {
        if (controller.signal.aborted) return;
        setView({ kind: "ready", token, connection: null, canConnect: true, reason: null });
      }
    })();
    return () => controller.abort();
  }, [handle]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!anchorRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  if (view.kind === "hidden") return null;

  const label = name ? `Connect with ${name}` : "Connect";

  function toggle() {
    if (!open && anchorRef.current) {
      // Keep the popover on screen: the pill sits in a narrow column beside the avatar. Open from the
      // pill's left edge; if that runs off the right, line up with its right edge when that fits (a
      // pill at the end of the actions), otherwise slide left just enough.
      const rect = anchorRef.current.getBoundingClientRect();
      const width = Math.min(POPOVER_WIDTH, window.innerWidth - 24);
      const maxLeft = window.innerWidth - 12 - width;
      let left = rect.left;
      if (left > maxLeft && rect.right - width >= 12) left = rect.right - width;
      left = Math.max(12, Math.min(left, maxLeft));
      setPopover({ left: left - rect.left, width });
    }
    setError("");
    setOpen(!open);
  }

  function close() {
    setOpen(false);
    pillRef.current?.focus();
  }

  async function send() {
    if (view.kind !== "ready") return;
    setBusy(true);
    setError("");
    try {
      const result = await cardsNetworkRequest<{ connection: CardConnection; existing: boolean }>(
        "/connections", view.token, "POST", { target_handle: handle, message: message.trim() || undefined },
      );
      const { id, status, incoming } = result.connection;
      setView({ ...view, connection: { id, status, incoming }, canConnect: false, reason: null });
      setNotice(connectionRequestNotice(result));
      setOpen(false);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not send the request");
    } finally {
      setBusy(false);
    }
  }

  async function accept(connection: ConnectionSummary) {
    if (view.kind !== "ready") return;
    setBusy(true);
    setNotice("");
    try {
      await cardsNetworkRequest(`/connections/${connection.id}/respond`, view.token, "POST", { action: "accept" });
      setView({ ...view, connection: { ...connection, status: "accepted" } });
      setNotice("Connection accepted");
    } catch (failure) {
      setNotice(failure instanceof Error ? failure.message : "Could not accept the request");
    } finally {
      setBusy(false);
    }
  }

  let pill: React.ReactNode;
  let hint: React.ReactNode = null;
  if (view.kind === "loading") {
    // Same size as the settled pill, so the hero does not jump when the answer arrives.
    pill = (
      <button type="button" className="pf-connect-pill" aria-disabled="true" aria-busy="true" aria-label="Checking your connection with this Card" tabIndex={-1}>
        <UserPlus size={14} aria-hidden="true" /> Connect
      </button>
    );
  } else if (view.kind === "signed-out") {
    pill = (
      <Link className="pf-connect-pill" href={`/auth?next=${encodeURIComponent(`/p/${encodeURIComponent(handle)}`)}`}>
        <UserPlus size={14} aria-hidden="true" /> Connect
      </Link>
    );
  } else {
    const state = connectionState(view.connection);
    if (state === "connected" && view.connection) {
      pill = (
        <Link className="pf-connect-pill" href={`/network?c=${view.connection.id}`}>
          <MessageCircle size={14} aria-hidden="true" /> Message
        </Link>
      );
    } else if (state === "wants-to-connect" && view.connection) {
      const connection = view.connection;
      pill = (
        <button type="button" className="pf-connect-pill" disabled={busy} onClick={() => void accept(connection)}>
          <Check size={14} aria-hidden="true" /> {busy ? "Accepting…" : "Accept"}
        </button>
      );
      hint = <span>{name ? `${name} wants` : "They want"} to connect with you.</span>;
    } else if (state === "requested") {
      pill = (
        <button type="button" className="pf-connect-pill" aria-disabled="true" title="Waiting for their answer">
          <Clock3 size={14} aria-hidden="true" /> Requested
        </button>
      );
    } else if (state === "closed" || !view.canConnect) {
      // Nothing can be sent: a decided connection is final, and without a Card of your own there is
      // no one to send it as. (Without a connection the only blocker is the missing Card.)
      pill = (
        <button type="button" className="pf-connect-pill" aria-disabled="true" aria-describedby="pf-connect-reason" title={view.reason ?? undefined}>
          <UserPlus size={14} aria-hidden="true" /> Connect
        </button>
      );
      hint = (
        <span id="pf-connect-reason">
          {view.reason}
          {state === "none" && <> <Link href="/create">Create your Card</Link></>}
        </span>
      );
    } else {
      pill = (
        <button
          ref={pillRef}
          type="button"
          className="pf-connect-pill"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={toggle}
        >
          <UserPlus size={14} aria-hidden="true" /> Connect
        </button>
      );
    }
  }

  return (
    <div className={variant === "edition" ? "pf-connect is-edition" : "pf-connect"}>
      <span className="pf-connect-anchor" ref={anchorRef}>
        {pill}
        {open && (
          <div
            className="pf-connect-pop"
            role="dialog"
            aria-label={label}
            style={{ left: popover.left, width: popover.width }}
            onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); close(); } }}
          >
            <p className="pf-connect-pop-text">DMs open after they accept.</p>
            <textarea
              autoFocus
              aria-label="Connection note"
              className="pf-connect-pop-note"
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              maxLength={2000}
              rows={3}
              placeholder="Optional note"
            />
            <div className="pf-connect-pop-actions">
              <button type="button" className="pf-connect-send" disabled={busy} onClick={() => void send()}>
                {busy ? "Sending…" : "Send request"}
              </button>
              <button type="button" className="pf-connect-cancel" onClick={close}>Cancel</button>
            </div>
            {error && <p className="pf-connect-pop-error" role="alert">{error}</p>}
          </div>
        )}
      </span>
      {hint && <span className="pf-connect-note">{hint}</span>}
      {notice && <span className="pf-connect-note" role="status">{notice}</span>}
    </div>
  );
}
