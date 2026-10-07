"use client";

import { QRCodeSVG } from "qrcode.react";
import { useState } from "react";
import { CraneLit } from "@/components/dear/ui";
import type { Letter } from "@/lib/dear/types";

type Tab = "link" | "qr" | "image" | "embed";

/**
 * Share (slice S07). The review's findings and what changed:
 *  - the QR was 136px in a popover → 320px here, with a full-screen mode to
 *    hold up across a table, and a quiet margin so phones can read it;
 *  - the link ended in a random suffix → a short address people can say aloud;
 *  - every profile unfurled with the same image → a per-person image, shown
 *    here exactly as it will look when pasted;
 *  - no signature or README snippets → both, ready to copy.
 */
export function ShareClient({ letter }: { letter: Letter }) {
  const [tab, setTab] = useState<Tab>("link");
  const [copied, setCopied] = useState<string | null>(null);
  const [full, setFull] = useState(false);
  const url = `https://dearagent.me/${letter.handle.split("-")[0]}`;
  const building = letter.facts.find((f) => f.kind === "building" && f.state === "ink")?.text ?? letter.headline;
  const looking = letter.facts.find((f) => f.kind === "looking_for" && f.state === "ink")?.text;

  async function copy(key: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
    } catch {
      setCopied(`${key}-failed`);
    }
  }

  const signature = `${letter.name}\n${letter.headline}\nMy letter to the agents: ${url}`;
  const readme = `[![Dear Agent](${url}/badge.svg)](${url})`;
  const tabs: [Tab, string][] = [
    ["link", "Link"],
    ["qr", "QR code"],
    ["image", "Preview image"],
    ["embed", "Signature & README"],
  ];

  return (
    <div className="stack-lg">
      <header className="stack">
        <h1 className="display" style={{ fontSize: "clamp(40px, 6vw, 60px)" }}>
          Replace your link in bio.
        </h1>
        <p className="lede">One link for who you are today. Every place you would paste a profile link, paste this instead.</p>
      </header>

      <div className="row" role="tablist">
        {tabs.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={tab === key} className={`btn small ${tab === key ? "agent" : "quiet"}`} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>

      {tab === "link" && (
        <section className="paper stack">
          <p className="m dim">Your address</p>
          <p style={{ fontSize: "clamp(28px, 6vw, 44px)", overflowWrap: "anywhere", userSelect: "all" }}>{url.replace("https://", "")}</p>
          <div className="row">
            <button className="btn" onClick={() => copy("link", url)}>
              {copied === "link" ? "Copied ✓" : "Copy link"}
            </button>
            <button className="btn quiet">Change address</button>
          </div>
          {copied === "link-failed" && <p className="m stale">Could not copy. Select the address above and copy it.</p>}
          <hr />
          <p className="m dim">Where it works hardest</p>
          <ul className="facts">
            <li className="fact">
              <span className="t">LinkedIn → Featured</span>
              <span className="src">People who find you there read what is true today</span>
            </li>
            <li className="fact">
              <span className="t">Email signature</span>
              <span className="src">Every email carries it</span>
            </li>
            <li className="fact">
              <span className="t">GitHub profile README</span>
              <span className="src">Where other builders, and their agents, look first</span>
            </li>
          </ul>
        </section>
      )}

      {tab === "qr" && (
        <section className="paper stack" style={{ alignItems: "flex-start" }}>
          <p className="m dim">Scan to read {letter.name.split(" ")[0]}&apos;s letter</p>
          <div className="qr">
            <QRCodeSVG value={url} size={320} marginSize={2} bgColor="#ece5d3" fgColor="#26221c" level="M" />
          </div>
          <div className="row">
            <button className="btn" onClick={() => setFull(true)}>
              Show full screen
            </button>
            <span className="m dim">For meetups: hold your phone up, they scan it</span>
          </div>
        </section>
      )}

      {tab === "image" && (
        <section className="stack">
          <p className="m dim">How it looks when you paste the link in LinkedIn, X or WhatsApp</p>
          <div className="panel" style={{ padding: 0, overflow: "hidden", maxWidth: 620 }}>
            <div style={{ aspectRatio: "1200 / 630", background: "radial-gradient(520px 320px at 12% 0%, rgba(242,194,122,.28), transparent 62%), #0d0f10", padding: "7%", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
              <div className="row between">
                <span className="m glow">Dear agent,</span>
                <CraneLit className="crane-hero" />
              </div>
              <div className="stack" style={{ gap: 6 }}>
                <span style={{ fontSize: "clamp(26px, 5.4vw, 44px)", lineHeight: 1 }}>{letter.name}</span>
                <span className="dim" style={{ fontSize: "clamp(15px, 2.6vw, 20px)" }}>
                  Building: {building}
                </span>
                {looking && (
                  <span className="glow" style={{ fontSize: "clamp(15px, 2.6vw, 20px)" }}>
                    Looking for: {looking}
                  </span>
                )}
              </div>
            </div>
            <div style={{ padding: "12px 16px", borderTop: "1px solid var(--line)" }}>
              <div style={{ fontSize: 19 }}>{letter.name} · a letter to the agents</div>
              <div className="m dim">dearagent.me</div>
            </div>
          </div>
        </section>
      )}

      {tab === "embed" && (
        <section className="stack-lg">
          <div className="panel stack">
            <h2 className="h3">Email signature</h2>
            <pre className="code">{signature}</pre>
            <button className="btn small quiet" style={{ alignSelf: "flex-start" }} onClick={() => copy("sig", signature)}>
              {copied === "sig" ? "Copied ✓" : "Copy signature"}
            </button>
          </div>
          <div className="panel stack">
            <h2 className="h3">GitHub README badge</h2>
            <pre className="code">{readme}</pre>
            <button className="btn small quiet" style={{ alignSelf: "flex-start" }} onClick={() => copy("readme", readme)}>
              {copied === "readme" ? "Copied ✓" : "Copy markdown"}
            </button>
          </div>
        </section>
      )}

      {full && (
        <div className="qr-full" role="dialog" aria-modal="true" aria-label="QR code, full screen">
          <QRCodeSVG value={url} size={Math.min(520, typeof window === "undefined" ? 520 : window.innerWidth - 64)} marginSize={2} bgColor="#ece5d3" fgColor="#26221c" level="M" />
          <p style={{ fontSize: 30, fontFamily: "var(--serif)" }}>{url.replace("https://", "")}</p>
          <button className="btn" style={{ background: "#26221c", borderColor: "#26221c", color: "#ece5d3" }} onClick={() => setFull(false)}>
            Done
          </button>
        </div>
      )}
    </div>
  );
}
