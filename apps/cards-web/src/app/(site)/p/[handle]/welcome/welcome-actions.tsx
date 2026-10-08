"use client";

import { useState } from "react";
import Link from "next/link";
import { ShareButton, QrButton } from "../share-controls";

interface WelcomeActionsProps {
  handle: string;
  firstName: string;
  action: "ask" | "looking" | "share" | "connect";
  claimed: boolean;
  canonical: string;
}

/** Per-step CTA on the first-win screen. The "ask your own card" button opens
 *  the profile chat via the window event the widget already listens for. */
export function WelcomeActions({ handle, firstName, action, claimed, canonical }: WelcomeActionsProps) {
  const [asked, setAsked] = useState(false);

  if (action === "ask") {
    if (!claimed) {
      return (
        <Link href={`/p/${encodeURIComponent(handle)}`} style={linkStyle}>
          Claim your card, then ask it →
        </Link>
      );
    }
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10, flexWrap: "wrap" }}>
        <button
          type="button"
          onClick={() => {
            window.dispatchEvent(new Event("zynd:open-profile-chat"));
            setAsked(true);
          }}
          style={btnStyle}
        >
          {asked ? "The assistant is open — ask away" : `Ask about ${firstName}`}
        </button>
        {asked && <span style={{ fontSize: 12, color: "#6E6E68" }}>bottom-right corner ↗</span>}
      </div>
    );
  }

  if (action === "looking") {
    return (
      <Link href={`/p/${encodeURIComponent(handle)}/edit`} style={{ ...linkStyle, marginTop: 10, display: "inline-block" }}>
        Set what you&apos;re looking for →
      </Link>
    );
  }

  if (action === "share") {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10, flexWrap: "wrap" }}>
        <ShareButton url={canonical} />
        <QrButton url={canonical} />
      </div>
    );
  }

  return (
    <Link href={`/p/${encodeURIComponent(handle)}/edit`} style={{ ...linkStyle, marginTop: 10, display: "inline-block" }}>
      Open memory &amp; MCP settings →
    </Link>
  );
}

const linkStyle: React.CSSProperties = {
  fontSize: 13.5,
  fontWeight: 600,
  color: "#7B72E9",
  textDecoration: "none",
};

const btnStyle: React.CSSProperties = {
  background: "#0B0B0B",
  color: "#fff",
  border: "none",
  borderRadius: 99,
  padding: "10px 18px",
  fontSize: 13.5,
  fontWeight: 700,
  cursor: "pointer",
};