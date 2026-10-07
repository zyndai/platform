"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ageLabel, KIND_LABEL, searchLetters } from "@/lib/dear/repo";
import type { SearchHit } from "@/lib/dear/types";

const EXAMPLES = [
  "founding engineer who has shipped payments",
  "someone who can review an MCP server",
  "design help for a developer tool onboarding",
];

/**
 * One search box for the whole product (the review found three). It asks the
 * way an agent would and shows *why* each person matched: the inked lines,
 * with their dates. Unclaimed letters are listed last and say so.
 */
export function AskBox({ initial = "", autoRun = false, limit }: { initial?: string; autoRun?: boolean; limit?: number }) {
  const [q, setQ] = useState(initial);
  const [hits, setHits] = useState<SearchHit[] | null>(null);

  async function run(query: string) {
    setQ(query);
    const found = await searchLetters(query);
    setHits(limit ? found.slice(0, limit) : found);
  }

  useEffect(() => {
    if (!autoRun) return;
    let live = true;
    searchLetters(initial).then((found) => {
      if (live) setHits(limit ? found.slice(0, limit) : found);
    });
    return () => {
      live = false;
    };
  }, [autoRun, initial, limit]);

  return (
    <div className="stack">
      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault();
          run(q);
        }}
      >
        <input id="ask-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask the way an agent would…" aria-label="Who are you looking for?" />
        <button className="btn agent" type="submit">
          Ask
        </button>
      </form>
      <div className="chips">
        {EXAMPLES.map((ex) => (
          <button key={ex} type="button" className="chip" onClick={() => run(ex)}>
            {ex}
          </button>
        ))}
      </div>

      {hits && (
        <div className="rows rise" aria-live="polite">
          {hits.length === 0 && <p className="dim">Nobody has written a letter that answers that yet.</p>}
          {hits.map(({ letter, reasons }) => (
            <article key={letter.handle} className="stack" style={{ gap: 8 }}>
              <div className="row between">
                <Link href={`/dear/l/${letter.handle}`} className="h3" style={{ textDecoration: "none" }}>
                  {letter.name}
                </Link>
                {letter.claimed ? (
                  <span className="stamp ok">updated {ageLabel(letter.updatedAt)}</span>
                ) : (
                  <span className="stamp warn">no letter yet · from public data</span>
                )}
              </div>
              <p className="dim">
                {letter.headline} · {letter.location}
              </p>
              {reasons.map((f) => (
                <p key={f.id} className="mono glow">
                  ↳ {KIND_LABEL[f.kind]}: {f.text} <span className="dim">({ageLabel(f.approvedAt ?? f.asOf)})</span>
                </p>
              ))}
              {!letter.claimed && <p className="mono dim">↳ Not shown to agents. They can be invited to write their letter.</p>}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
