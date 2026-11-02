"use client";

import { useState } from "react";
import { ArrowUpRight } from "lucide-react";
import type { Beacon } from "@/lib/cards";
import { endsIn, hostnameOf, kindLabel, liveFromBeacon, safeAskUrl, type LiveAsk } from "@/lib/asks";
import { AskComposer, type ComposerAuthor } from "./AskComposer";

/**
 * The ask on the edit page: a short summary of the live one and a button that opens the same composer
 * as the feed's Post button, so there is one way to post an ask everywhere.
 */
export function EditPageAsk({
  token,
  initial,
  author,
}: {
  token: string;
  initial?: Beacon | null;
  author: ComposerAuthor;
}) {
  const [nowMs] = useState(() => Date.now());
  const [live, setLive] = useState<LiveAsk | null>(() => liveFromBeacon(initial, nowMs));
  const [mode, setMode] = useState<null | "new" | "edit">(null);
  const [notice, setNotice] = useState("");
  const href = safeAskUrl(live?.url);

  return (
    <section className="pe-card" id="beacon" style={{ padding: 24, marginBottom: 20 }}>
      <h2 style={{ marginTop: 0 }}>Your ask</h2>
      <p>Tell people what you need right now: a team, a co-founder, early users. It stays up for seven days and is sent to people who match.</p>
      {live ? (
        <div aria-label="Your live ask" role="group">
          <p><strong>{kindLabel(live.kind)}</strong> · {endsIn(live.expires_at, nowMs)}</p>
          <p style={{ overflowWrap: "anywhere" }}>{live.text}</p>
          {href && (
            <p>
              <a href={href} target="_blank" rel="noopener noreferrer nofollow ugc">
                {hostnameOf(href)} <ArrowUpRight size={13} aria-hidden="true" />
              </a>
            </p>
          )}
        </div>
      ) : (
        <p>You don&apos;t have a live ask.</p>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 12 }}>
        {live ? (
          <button type="button" className="pe-btn pe-btn-primary" onClick={() => setMode("edit")}>Edit your ask</button>
        ) : (
          <button type="button" className="pe-btn pe-btn-primary" onClick={() => setMode("new")}>Post an ask</button>
        )}
      </div>
      <p role="status">{notice}</p>
      <AskComposer
        open={mode !== null}
        edit={mode === "edit"}
        onClose={() => setMode(null)}
        getToken={async () => token}
        hasCard
        author={author}
        live={live}
        onPosted={(ask) => {
          setLive(ask);
          setMode(null);
          setNotice("Your ask is live for 7 days.");
        }}
        onTakenDown={() => {
          setLive(null);
          setMode(null);
          setNotice("Your ask is down.");
        }}
      />
    </section>
  );
}
