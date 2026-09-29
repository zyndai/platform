"use client";

import { useCallback, useState } from "react";
import { ArrowUpRight, Check, Copy, MessageCircle } from "lucide-react";

export function HeroAskPanel({ firstName, handle, permalink }: { firstName: string; handle: string; permalink: string }) {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(`https://${permalink}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* ignore */
    }
  }, [permalink]);

  return (
    <div
      style={{
        flex: 1,
        minHeight: 108,
        marginTop: 14,
        background: "rgba(255,255,255,0.14)",
        border: "1px solid rgba(255,255,255,0.2)",
        borderRadius: 16,
        padding: "12px 14px",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        gap: 10,
      }}
    >
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.78rem", fontWeight: 800 }}>
          <MessageCircle size={14} />
          Ask {firstName}
        </div>
        <p style={{ margin: "4px 0 0", fontSize: "0.7rem", lineHeight: 1.4, color: "rgba(255,255,255,0.82)", fontWeight: 500 }}>
          Work, stack, what they are building. The agent answers from this card.
        </p>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <button
          type="button"
          onClick={() => window.dispatchEvent(new Event("zynd:open-profile-chat"))}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            border: "none",
            background: "#fff",
            color: "#4f46e5",
            borderRadius: 10,
            padding: "8px 12px",
            fontSize: "0.75rem",
            fontWeight: 800,
            cursor: "pointer",
          }}
        >
          Open chat
          <ArrowUpRight size={14} />
        </button>
        <button
          type="button"
          onClick={copy}
          className="pf-mono"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            border: "1px solid rgba(255,255,255,0.28)",
            background: "transparent",
            color: "#fff",
            borderRadius: 10,
            padding: "8px 10px",
            fontSize: "0.62rem",
            fontWeight: 700,
            cursor: "pointer",
          }}
          aria-label={copied ? "Copied profile link" : "Copy profile link"}
        >
          {copied ? <Check size={11} /> : <Copy size={11} />}
          {copied ? "Copied" : `@${handle}`}
        </button>
      </div>
    </div>
  );
}
