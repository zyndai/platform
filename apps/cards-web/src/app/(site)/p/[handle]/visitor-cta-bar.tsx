"use client";

import { useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { X } from "lucide-react";
import { track } from "@/lib/track";

const DISMISS_KEY = "zynd:visitor-cta-dismissed";

function subscribeToDismissal(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

function readStoredDismissal(): boolean {
  try {
    return window.localStorage.getItem(DISMISS_KEY) !== null;
  } catch {
    // Storage blocked (private mode, disabled site data): show the bar; dismissal then lasts this visit only.
    return false;
  }
}

// Hidden until hydration so a visitor who already dismissed it never sees it flash in.
function readServerDismissal(): boolean {
  return true;
}

/** Shown only to viewers who are neither the owner nor a card holder (decided by
 *  the page). Stacks under the chat widget (z 50) and share/QR overlays (z 100+);
 *  on desktop it stops short of the chat button's corner, and on phones it stays
 *  under the button's 76px bottom offset (sub-line clamped to keep it that short). */
export function VisitorCtaBar({ handle }: { handle: string }) {
  const isStoredDismissed = useSyncExternalStore(subscribeToDismissal, readStoredDismissal, readServerDismissal);
  const [isDismissedThisVisit, setIsDismissedThisVisit] = useState(false);
  if (isStoredDismissed || isDismissedThisVisit) return null;

  // `ref` rides the existing attribution cookie (proxy.ts) into onboarding and the card row.
  const createHref = `/create?${new URLSearchParams({ ref: "card_bar", from: handle })}`;

  function dismiss() {
    setIsDismissedThisVisit(true);
    try {
      window.localStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch (err) {
      console.warn("visitor CTA: could not remember dismissal", err);
    }
  }

  return (
    <>
      <div className="pf-cta-spacer" aria-hidden />
      <aside className="pf-cta-bar" aria-label="Get your own Zynd card">
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="pf-cta-title" style={{ color: "#0f172a" }}>
            Get your own Zynd card
          </div>
          <div className="pf-cta-sub" style={{ color: "#64748b" }}>
            Free. Built from your links in about a minute.
          </div>
        </div>
        {/* No prefetch: proxy.ts runs on prefetches too and would stamp ref=card_bar on visitors who never clicked. */}
        <Link
          href={createHref}
          prefetch={false}
          className="pf-cta-btn"
          onClick={() => track("visitor_cta_click", { target: "card_bar" }, handle)}
          style={{
            background: "#0B0B0B", color: "#fff", borderRadius: 99, padding: "0 16px", height: 36,
            display: "inline-flex", alignItems: "center", fontSize: 13, fontWeight: 700, whiteSpace: "nowrap", flexShrink: 0,
          }}
        >
          Get yours
        </Link>
        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss"
          style={{
            background: "transparent", border: "none", color: "#94a3b8", cursor: "pointer", flexShrink: 0,
            width: 32, height: 32, display: "inline-flex", alignItems: "center", justifyContent: "center", borderRadius: 99,
          }}
        >
          <X size={16} aria-hidden />
        </button>
      </aside>
      <style>{`
        .pf-cta-spacer { height: 96px; }
        .pf-cta-bar {
          position: fixed; z-index: 40; bottom: 24px; left: 24px; right: 96px; margin: 0 auto; max-width: 560px;
          display: flex; align-items: center; gap: 12px; padding: 12px 10px 12px 18px;
          background: #fff; border: 1px solid #e2e8f0; border-radius: 16px;
          box-shadow: 0 10px 30px -12px rgba(15, 23, 42, 0.25);
          animation: pf-cta-in 220ms ease-out;
        }
        .pf-cta-title { font-size: 14px; font-weight: 700; line-height: 18px; }
        .pf-cta-sub { font-size: 12.5px; line-height: 16px; margin-top: 2px; }
        .pf-cta-bar a.pf-cta-btn:hover { text-decoration: none; opacity: 0.88; }
        .pf-cta-bar a.pf-cta-btn:focus-visible { outline: 2px solid #0B0B0B; outline-offset: 2px; }
        @keyframes pf-cta-in { from { transform: translateY(12px); opacity: 0; } to { transform: none; opacity: 1; } }
        @media (prefers-reduced-motion: reduce) { .pf-cta-bar { animation: none; } }
        @media (max-width: 820px) {
          .pf-cta-spacer { height: calc(80px + env(safe-area-inset-bottom, 0px)); }
          .pf-cta-bar {
            left: 0; right: 0; bottom: 0; max-width: none; border-radius: 0; border-width: 1px 0 0;
            gap: 10px; padding: 9px 8px calc(9px + env(safe-area-inset-bottom, 0px)) 16px;
          }
          .pf-cta-title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
          .pf-cta-sub {
            font-size: 12px; line-height: 15px; margin-top: 1px;
            display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
          }
        }
      `}</style>
    </>
  );
}
