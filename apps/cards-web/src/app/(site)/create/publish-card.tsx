"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, TriangleAlert } from "lucide-react";

import { AlternateSignIn } from "@/components/auth/alternate-sign-in";
import { slugifyHandle } from "./model";
import { handleIsFree } from "./publish";

/** How long after the last keystroke the slug is checked. */
const CHECK_DELAY_MS = 400;

/** The last step: pick a link, and publish when the draft is ready. */
export function PublishCard({ ready, building, hasSource, statusText, handle, onHandle, authenticated, onSignIn, onBeforeAlternateSignIn, onPublish, publishing, error }: {
  ready: boolean;
  building: boolean;
  hasSource: boolean;
  statusText: string;
  handle: string;
  onHandle: (slug: string) => void;
  authenticated: boolean;
  onSignIn: () => void;
  /** Google / email sign-in (behind flags): save the draft before leaving. */
  onBeforeAlternateSignIn: () => void;
  onPublish: () => void;
  publishing: boolean;
  error: string | null;
}) {
  const [free, setFree] = useState<boolean | null>(null);
  const [checking, setChecking] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const change = (raw: string) => {
    const slug = slugifyHandle(raw);
    onHandle(slug);
    setFree(null);
    if (timer.current) clearTimeout(timer.current);
    if (slug.length < 2) { setChecking(false); return; }
    setChecking(true);
    timer.current = setTimeout(async () => {
      setFree(await handleIsFree(slug));
      setChecking(false);
    }, CHECK_DELAY_MS);
  };

  const showStatus = handle.length >= 2;
  const tone = checking ? "var(--dc-faint)" : free === false ? "#B91C1C" : free === true ? "#14663A" : "var(--dc-faint)";

  return (
    <section className="cr-publish" aria-label="Publish">
      <div className="cr-field">
        <span className="dc-label">Your link <span className="cr-note">optional</span></span>
        <div className="cr-handle">
          <span className="cr-prefix" aria-hidden="true">zynd.ai/p/</span>
          <input
            className="cr-input" value={handle} placeholder="your-name" aria-label="Custom profile link"
            autoComplete="off" autoCapitalize="off" spellCheck={false}
            onChange={(e) => change(e.target.value)}
          />
          {showStatus && (
            <span className="cr-ok" style={{ color: tone }}>
              {checking ? "checking…" : free === false ? "taken" : free === true ? "available ✓" : ""}
            </span>
          )}
        </div>
      </div>

      {error && <div className="cr-alert" role="alert"><TriangleAlert size={16} aria-hidden="true" /> {error}</div>}

      <button type="button" className="dc-btn dc-btn-primary cr-go" disabled={!ready || publishing} onClick={onPublish}>
        {publishing ? "Publishing…" : "Publish my card"} {!publishing && <ArrowRight size={17} aria-hidden="true" />}
      </button>

      <div className="cr-note" role="status">
        {!hasSource ? "Add a profile link to start your card."
          : building ? statusText
          : ready ? "Nothing is public until you publish."
          : statusText}
      </div>

      {!authenticated && (
        <>
          <hr className="cr-divider" />
          <div className="cr-note">
            Sign in first to own your card from the start, or publish now and claim it afterwards.
          </div>
          <button type="button" className="dc-btn dc-btn-ghost cr-ghost-btn" onClick={onSignIn}>Sign in with LinkedIn</button>
          <AlternateSignIn
            next="/create" intent="card" onBeforeSignIn={onBeforeAlternateSignIn}
            buttonClassName="dc-btn dc-btn-ghost cr-ghost-btn"
          />
        </>
      )}
    </section>
  );
}
