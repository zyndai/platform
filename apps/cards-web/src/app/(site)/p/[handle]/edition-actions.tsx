"use client";

import { useState } from "react";
import { ArrowUpRight, Check, Copy } from "lucide-react";

/** Open chat + copy-link buttons of the edition identity card. Same actions as
 *  the classic hero's Ask panel (hero-agent-bar.tsx), laid out as in the mockup. */
export function EditionIdentityActions({ handle, permalink, canChat }: { handle: string; permalink: string; canChat: boolean }) {
  const [copied, setCopied] = useState(false);

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(`https://${permalink}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch (err) {
      // Clipboard can be blocked (insecure context, permissions); the link is still printed on the card.
      console.warn("edition card: copy link failed", err);
    }
  }

  return (
    <div className="ed-id-buttons">
      {canChat && (
        <button type="button" className="ed-btn-primary" onClick={() => window.dispatchEvent(new Event("zynd:open-profile-chat"))}>
          Open chat <ArrowUpRight size={17} aria-hidden />
        </button>
      )}
      <button type="button" className="ed-btn-outline" onClick={copyLink} aria-label={copied ? "Copied profile link" : "Copy profile link"}>
        {copied ? <Check size={15} aria-hidden /> : <Copy size={15} aria-hidden />}
        <span>{copied ? "Copied" : `@${handle}`}</span>
      </button>
    </div>
  );
}
