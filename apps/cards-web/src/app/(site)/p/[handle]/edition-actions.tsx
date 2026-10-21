"use client";

import { useState } from "react";
import { Bot, Check, Copy } from "lucide-react";

/** Ask Agent + copy-link buttons of the edition identity card. "Ask Agent"
 *  opens the card's AI agent (the profile chat widget); talking to the person
 *  themselves is a DM, after connecting. Rendered as siblings so they share
 *  one row of the action grid. */
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
    <>
      {canChat && (
        <button type="button" className="ed-btn ed-btn-soft" onClick={() => window.dispatchEvent(new Event("zynd:open-profile-chat"))}>
          <Bot size={17} aria-hidden /> Ask Agent
        </button>
      )}
      <button type="button" className="ed-btn ed-btn-outline" onClick={copyLink} aria-label={copied ? "Copied profile link" : "Copy profile link"}>
        {copied ? <Check size={15} aria-hidden /> : <Copy size={15} aria-hidden />}
        <span className="ed-btn-handle">{copied ? "Copied" : `@${handle}`}</span>
      </button>
    </>
  );
}
