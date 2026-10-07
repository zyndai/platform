"use client";

import { useState } from "react";
import { AgentNote } from "@/components/dear/ui";
import { ageLabel } from "@/lib/dear/repo";
import type { SourceConnection } from "@/lib/dear/types";

const GROUP_TITLE: Record<SourceConnection["group"], string> = {
  profile: "Who you are",
  work: "What you ship and say",
  assistant: "The AI you work with",
};

/**
 * Sources (slice S09). One place that shows where every line comes from.
 * Changes from the current "Add MCP" panel:
 *  - one click to connect, no JSON to paste, no key shown to non-developers;
 *  - each assistant is listed and can be disconnected by itself (today
 *    "Disconnect" signs out every connected assistant at once);
 *  - each source says when it was last read and what it contributed;
 *  - no source can publish without a tap. That is stated, not configurable.
 */
export function SourcesClient({ initial }: { initial: SourceConnection[] }) {
  const [sources, setSources] = useState(initial);
  const [showDev, setShowDev] = useState(false);

  function toggle(id: string) {
    setSources((list) => list.map((s) => (s.id === id ? { ...s, connected: !s.connected, lastRead: s.connected ? undefined : "2026-10-08" } : s)));
  }

  return (
    <div className="stack-lg">
      <header className="stack">
        <h1 className="display" style={{ fontSize: "clamp(40px, 6vw, 60px)" }}>
          Where your letter comes from.
        </h1>
        <p className="lede">Your agent reads these and pencils in what it finds. It never writes in ink. Only you do.</p>
      </header>

      {(["profile", "work", "assistant"] as const).map((group) => (
        <section key={group} className="paper stack">
          <h2 className="h3">{GROUP_TITLE[group]}</h2>
          <div className="rows">
            {sources
              .filter((s) => s.group === group)
              .map((s) => (
                <div key={s.id} className="row between" style={{ alignItems: "flex-start" }}>
                  <div className="stack" style={{ gap: 4, minWidth: 0, flex: "1 1 320px" }}>
                    <span style={{ fontSize: 25 }}>{s.label}</span>
                    <span className="dim" style={{ fontSize: 18 }}>
                      {s.goodFor}
                    </span>
                    {s.connected ? (
                      <span className="m" style={{ color: "var(--ok)" }}>
                        <span className="dot" />
                        connected · last read {s.lastRead ? ageLabel(s.lastRead) : "never"} · {s.inked} in ink · {s.pencilled} in pencil
                      </span>
                    ) : (
                      <span className="m dim">not connected</span>
                    )}
                  </div>
                  <button className={`btn small ${s.connected ? "quiet" : "agent"}`} onClick={() => toggle(s.id)}>
                    {s.connected ? `Disconnect ${s.label}` : `Connect ${s.label}`}
                  </button>
                </div>
              ))}
          </div>
          {group === "assistant" && (
            <>
              <AgentNote>
                <div>I hear from your assistants when you finish something: a release, a new project, the end of a session. I do not report every keystroke, and I drop repository names and one-off tasks.</div>
              </AgentNote>
              <button className="tap" style={{ alignSelf: "flex-start" }} aria-expanded={showDev} onClick={() => setShowDev(!showDev)}>
                {showDev ? "Hide" : "Using another tool? Connect it by hand"}
              </button>
              {showDev && (
                <pre className="code">{`{
  "mcpServers": {
    "dear-agent": { "url": "https://api.zynd.ai/mcp" }
  }
}
// Sign in when your tool asks. No key to copy.`}</pre>
              )}
            </>
          )}
        </section>
      ))}

      <section className="panel stack">
        <h2 className="h3">Your data</h2>
        <p className="dim">Everything in ink, with its sources and dates, in one file. Yours to take anywhere.</p>
        <div className="row">
          <button className="btn small quiet">Export my letter</button>
          <button className="btn small quiet">Hide my letter from AI crawlers</button>
          <button className="btn small quiet">Delete my letter</button>
        </div>
      </section>
    </div>
  );
}
