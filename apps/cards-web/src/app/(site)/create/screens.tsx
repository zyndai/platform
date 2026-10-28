"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, ArrowUpRight, Check } from "lucide-react";

import { AlternateSignIn } from "@/components/auth/alternate-sign-in";
import { setClaimHandle } from "@/lib/auth/next-cookie";
import { alternateSignInEnabled } from "@/lib/auth/providers";

const COPIED_MS = 1600;

/** The card is live and was published without signing in. */
export function PublishedScreen({ handle, authenticated, onClaim }: { handle: string; authenticated: boolean; onClaim: () => void }) {
  const [copied, setCopied] = useState(false);
  const url = `zynd.ai/p/${handle}`;

  return (
    <section className="cr-center" aria-labelledby="cr-live-h">
      <span className="cr-tick"><Check size={26} strokeWidth={2.6} aria-hidden="true" /></span>
      <div style={{ display: "grid", gap: 8, justifyItems: "center" }}>
        <span className="dc-label">Published</span>
        <div id="cr-live-h" role="heading" aria-level={1} className="dc-title" style={{ margin: 0, textAlign: "center" }}>You&apos;re live</div>
        <span className="cr-live-url">
          {url}
          <button
            type="button" className="dc-btn dc-btn-ghost" style={{ height: 30, padding: "0 12px", fontSize: 12 }}
            onClick={() => { navigator.clipboard?.writeText(`https://${url}`).catch(() => {}); setCopied(true); setTimeout(() => setCopied(false), COPIED_MS); }}
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </span>
        <p className="cr-sub" style={{ maxWidth: 360 }}>
          Discoverable by AI agents right now. Sign in to claim it so you can edit it anytime.
        </p>
      </div>
      <div className="cr-actions">
        <Link href={`/p/${encodeURIComponent(handle)}`} className="dc-btn dc-btn-primary cr-go">View my profile <ArrowRight size={17} aria-hidden="true" /></Link>
        {authenticated ? (
          <Link href={`/p/${encodeURIComponent(handle)}/edit`} className="dc-btn dc-btn-ghost cr-ghost-btn">Edit my card</Link>
        ) : (
          <button type="button" className="dc-btn dc-btn-ghost cr-ghost-btn" onClick={onClaim}>Claim with LinkedIn</button>
        )}
      </div>
      {alternateSignInEnabled && !authenticated && (
        <div style={{ width: "100%" }}>
          <AlternateSignIn
            next={`/p/${encodeURIComponent(handle)}`} intent="card" onBeforeSignIn={() => setClaimHandle(handle)}
            buttonClassName="dc-btn dc-btn-ghost cr-ghost-btn"
          />
        </div>
      )}
    </section>
  );
}

/** The signed-in person already has a card: one per person, so send them to it. */
export function AlreadyHaveCard({ handle, published }: { handle: string; published: boolean }) {
  return (
    <section className="cr-center" aria-labelledby="cr-have-h">
      <div style={{ display: "grid", gap: 8, justifyItems: "center" }}>
        <div id="cr-have-h" role="heading" aria-level={1} className="dc-title" style={{ margin: 0, textAlign: "center" }}>
          {published ? "Your card is live." : "Your card is not published yet."}
        </div>
        <p className="cr-sub" style={{ maxWidth: 380 }}>
          {published
            ? "Edit it anytime or share the link. Each person has one card."
            : "It was left in review by an earlier version of the flow. Edit and save it to publish."}
        </p>
      </div>
      <div className="cr-actions">
        <Link href={`/p/${encodeURIComponent(handle)}/edit`} className="dc-btn dc-btn-primary cr-go">
          {published ? "Edit my card" : "Finish publishing"} <ArrowRight size={17} aria-hidden="true" />
        </Link>
        {published && (
          <Link href={`/p/${encodeURIComponent(handle)}`} className="dc-btn dc-btn-ghost cr-ghost-btn">View profile <ArrowUpRight size={15} aria-hidden="true" /></Link>
        )}
      </div>
    </section>
  );
}

/** Publish found a card these profiles already have. */
export function CardExists({ handle, authenticated }: { handle: string; authenticated: boolean }) {
  return (
    <section className="cr-center" aria-labelledby="cr-exists-h">
      <div style={{ display: "grid", gap: 8, justifyItems: "center" }}>
        <div id="cr-exists-h" role="heading" aria-level={1} className="dc-title" style={{ margin: 0, textAlign: "center" }}>
          {authenticated ? "You already have a card." : "This profile already has a card."}
        </div>
        <p className="cr-sub" style={{ maxWidth: 400 }}>
          {authenticated
            ? "Each person has one card, so this one wasn't published. Edit your existing card to add anything new."
            : "A card for this GitHub or X profile already exists. If it's yours, open it and sign in with LinkedIn to claim it."}
        </p>
      </div>
      <div className="cr-actions">
        {authenticated && (
          <Link href={`/p/${encodeURIComponent(handle)}/edit`} className="dc-btn dc-btn-primary cr-go">Edit my card <ArrowRight size={17} aria-hidden="true" /></Link>
        )}
        <Link href={`/p/${encodeURIComponent(handle)}`} className={`dc-btn cr-ghost-btn ${authenticated ? "dc-btn-ghost" : "dc-btn-primary"}`}>
          {authenticated ? "View my card" : "Open the card"} <ArrowUpRight size={15} aria-hidden="true" />
        </Link>
      </div>
    </section>
  );
}
