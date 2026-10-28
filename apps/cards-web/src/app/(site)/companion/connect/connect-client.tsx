"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  BRIDGE_FROM_EXTENSION,
  BRIDGE_FROM_PAGE,
  browserLabel,
  listCompanionDevices,
  pairCompanion,
  removeMyExploring,
  revokeCompanionDevice,
  type CompanionDevice,
  type FromExtension,
} from "@/lib/companion";
import type { ExploringItem } from "@/lib/cards";

type Phase = "searching" | "missing" | "ready" | "connecting" | "connected" | "error";

const FIND_EXTENSION_MS = 2500;
// The extension checks the token with one API call (10s timeout, apps/zynd-companion/src/api.ts)
// after its service worker wakes, which can take seconds. Taking the token back before that call
// can finish would revoke a token the extension is about to keep.
const CONFIRM_MS = 20_000;

const PANEL = "rounded-2xl border border-white/10 bg-white/5 p-6";
const PRIMARY = "rounded-full bg-[#5b7cfa] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#4a6af0] disabled:opacity-50";
const QUIET = "rounded-full border border-white/15 px-4 py-2 text-sm text-zinc-200 hover:bg-white/10 disabled:opacity-50";

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function ConnectClient({
  state,
  token,
  account,
  exploring,
}: {
  state: string;
  token: string;
  account: { name: string; handle: string; headline: string } | null;
  exploring: ExploringItem[];
}) {
  const [phase, setPhase] = useState<Phase>(state ? "searching" : "missing");
  const [message, setMessage] = useState("");
  const [devices, setDevices] = useState<CompanionDevice[] | null>(null);
  const [clips, setClips] = useState<ExploringItem[]>(exploring);
  const [removing, setRemoving] = useState<string | null>(null);
  const [clipError, setClipError] = useState("");
  const minted = useRef<string | null>(null);
  // Set once an unconfirmed token is taken back: a "paired" arriving after that is for a dead token.
  const gaveUp = useRef(false);

  const loadDevices = useCallback(async () => {
    try {
      setDevices(await listCompanionDevices(token));
    } catch {
      setDevices([]);
    }
  }, [token]);

  useEffect(() => {
    const first = window.setTimeout(() => void loadDevices(), 0);
    return () => window.clearTimeout(first);
  }, [loadDevices]);

  // The extension's content script is the only thing that answers on this page.
  useEffect(() => {
    if (!state) return;
    const origin = window.location.origin;
    const onMessage = (event: MessageEvent) => {
      if (event.source !== window || event.origin !== origin) return;
      const data = event.data as Partial<FromExtension> | null;
      if (!data || data.source !== BRIDGE_FROM_EXTENSION || data.state !== state) return;
      if (data.type === "ready") setPhase((p) => (p === "searching" || p === "missing" ? "ready" : p));
      if (data.type === "paired") {
        if (gaveUp.current) return;
        minted.current = null;
        setPhase("connected");
        void loadDevices();
      }
      if (data.type === "rejected") {
        setMessage(data.reason || "The extension did not accept the connection.");
        setPhase("error");
      }
    };
    window.addEventListener("message", onMessage);
    const hello = () => window.postMessage({ source: BRIDGE_FROM_PAGE, type: "hello" }, origin);
    hello();
    const again = window.setTimeout(hello, 500);
    const giveUp = window.setTimeout(() => setPhase((p) => (p === "searching" ? "missing" : p)), FIND_EXTENSION_MS);
    return () => {
      window.removeEventListener("message", onMessage);
      window.clearTimeout(again);
      window.clearTimeout(giveUp);
    };
  }, [state, loadDevices]);

  async function connect() {
    setPhase("connecting");
    setMessage("");
    gaveUp.current = false;
    try {
      const paired = await pairCompanion(token, browserLabel(navigator.userAgent));
      minted.current = paired.device.id;
      window.postMessage(
        { source: BRIDGE_FROM_PAGE, type: "grant", state, token: paired.token, profile: paired.profile },
        window.location.origin,
      );
      // A token the extension never confirmed is a loose end: take it back.
      window.setTimeout(() => {
        if (minted.current !== paired.device.id) return;
        minted.current = null;
        gaveUp.current = true;
        void revokeCompanionDevice(token, paired.device.id).then(loadDevices, () => undefined);
        // Keep the extension's own reason when it already said no.
        setMessage((shown) => shown || "The extension did not confirm. Open it and choose Connect again.");
        setPhase("error");
      }, CONFIRM_MS);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not connect. Please try again.");
      setPhase("error");
    }
  }

  async function removeClip(url: string) {
    setRemoving(url);
    setClipError("");
    try {
      setClips(await removeMyExploring(token, url));
    } catch (error) {
      setClipError(error instanceof Error ? error.message : "Could not remove it. Please try again.");
    } finally {
      setRemoving(null);
    }
  }

  async function revoke(id: string) {
    try {
      await revokeCompanionDevice(token, id);
    } finally {
      void loadDevices();
    }
  }

  return (
    <main className="mx-auto w-full max-w-[640px] px-6 pb-32 pt-12 text-white antialiased">
      <h1 className="text-3xl font-bold md:text-4xl">Zynd Companion</h1>
      <p className="mt-3 text-zinc-400">
        Connect the browser extension to your account, or see which browsers are connected.{" "}
        <Link href="/companion" className="text-[#5b7cfa] underline underline-offset-4 hover:text-white">What is this?</Link>
      </p>

      {!account && (
        <section className={`${PANEL} mt-8`}>
          <h2 className="text-lg font-bold">Create your card first</h2>
          <p className="mt-2 text-zinc-300">Zynd Companion updates your card, so you need one before you can connect.</p>
          <Link href="/create" className={`${PRIMARY} mt-4 inline-block`}>Create your card</Link>
        </section>
      )}

      {account && !state && (
        <section className={`${PANEL} mt-8`}>
          <h2 className="text-lg font-bold">Start from the extension</h2>
          <p className="mt-2 text-zinc-300">
            Open Zynd Companion in your browser and choose <strong className="text-white">Connect Zynd account</strong>.
            It brings you back to this page to finish.
          </p>
        </section>
      )}

      {account && state && (
        <section className={`${PANEL} mt-8`} aria-live="polite">
          {phase === "searching" && <p className="text-zinc-300">Looking for Zynd Companion in this browser…</p>}

          {phase === "missing" && (
            <>
              <h2 className="text-lg font-bold">We could not find the extension</h2>
              <p className="mt-2 text-zinc-300">
                Open this page from Zynd Companion itself: click its icon in the toolbar and choose{" "}
                <strong className="text-white">Connect Zynd account</strong>. If it is not installed in this
                browser, install it first. Nothing has been connected.
              </p>
            </>
          )}

          {(phase === "ready" || phase === "connecting") && (
            <>
              <h2 className="text-lg font-bold">Connect Zynd Companion to {account.name || account.handle}?</h2>
              <p className="mt-1 text-sm text-zinc-400">cards.zynd.ai/p/{account.handle}</p>
              <div className="mt-5 grid gap-5 sm:grid-cols-2">
                <div>
                  <h3 className="text-sm font-bold text-white">It can</h3>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-zinc-300">
                    <li>Add or remove lines in Working On</li>
                    <li>Add or remove Currently exploring links, after you press Add</li>
                    <li>Show your name and photo in its window</li>
                  </ul>
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white">It cannot</h3>
                  <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-zinc-300">
                    <li>Read your messages or connections</li>
                    <li>Change your name, photo, links or settings</li>
                    <li>Publish anything else, or see what you browse</li>
                  </ul>
                </div>
              </div>
              <div className="mt-6 flex flex-wrap gap-3">
                <button type="button" className={PRIMARY} disabled={phase === "connecting"} onClick={() => void connect()}>
                  {phase === "connecting" ? "Connecting…" : "Connect"}
                </button>
                <Link href="/home" className={QUIET}>Cancel</Link>
              </div>
            </>
          )}

          {phase === "connected" && (
            <>
              <h2 className="text-lg font-bold">Connected</h2>
              <p className="mt-2 text-zinc-300">Zynd Companion is connected to {account.name || account.handle}. You can close this tab.</p>
            </>
          )}

          {phase === "error" && (
            <>
              <h2 className="text-lg font-bold">Not connected</h2>
              <p className="mt-2 text-zinc-300" role="alert">{message}</p>
            </>
          )}
        </section>
      )}

      {account && clips.length > 0 && (
        <section className={`${PANEL} mt-8`} aria-label="Currently exploring on your card">
          <h2 className="text-lg font-bold">Currently exploring</h2>
          <p className="mt-1 text-sm text-zinc-400">
            Links you added from the extension. Your card shows the last 30 days; remove any you no longer want there.
          </p>
          <ul className="mt-3 divide-y divide-white/10">
            {clips.map((clip) => (
              <li key={clip.url} className="flex items-center justify-between gap-4 py-3">
                <div className="min-w-0">
                  <div className="truncate font-semibold">{clip.title || clip.url}</div>
                  <div className="truncate text-xs text-zinc-500" title={clip.url}>
                    {clip.url} · added {when(clip.added_at)}
                  </div>
                </div>
                <button
                  type="button"
                  className={QUIET}
                  disabled={removing !== null}
                  aria-label={`Remove ${clip.title || clip.url}`}
                  onClick={() => void removeClip(clip.url)}
                >
                  {removing === clip.url ? "Removing…" : "Remove"}
                </button>
              </li>
            ))}
          </ul>
          {clipError && <p className="mt-2 text-sm text-red-300" role="alert">{clipError}</p>}
        </section>
      )}

      <section className={`${PANEL} mt-8`}>
        <h2 className="text-lg font-bold">Connected browsers</h2>
        {devices === null && <p className="mt-2 text-sm text-zinc-400">Loading…</p>}
        {devices?.length === 0 && <p className="mt-2 text-sm text-zinc-400">No browsers are connected.</p>}
        {devices && devices.length > 0 && (
          <ul className="mt-3 divide-y divide-white/10">
            {devices.map((device) => (
              <li key={device.id} className="flex items-center justify-between gap-4 py-3">
                <div className="min-w-0">
                  <div className="truncate font-semibold">{device.label || "Browser"}</div>
                  <div className="text-xs text-zinc-500">
                    Connected {when(device.created_at)} · last used {when(device.last_used_at)}
                  </div>
                </div>
                <button type="button" className={QUIET} onClick={() => void revoke(device.id)}>Disconnect</button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
