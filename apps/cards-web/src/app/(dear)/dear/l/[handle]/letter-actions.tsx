"use client";

import { useState } from "react";
import { AgentNote } from "@/components/dear/ui";
import { KIND_LABEL } from "@/lib/dear/repo";
import type { Letter } from "@/lib/dear/types";

const ASKS = ["A 20-minute call", "An email reply", "An introduction to someone they know"];

/**
 * "Say hello": the conversion event the review found missing (slice S12).
 * A visitor, or their agent, says who they are and why. The owner's agent
 * carries it home and the owner approves or declines. No contact details are
 * shown until they do.
 */
export function SayHello({ letter }: { letter: Letter }) {
  const [open, setOpen] = useState(false);
  const [sent, setSent] = useState(false);
  const [who, setWho] = useState("");
  const [why, setWhy] = useState("");
  const [asks, setAsks] = useState<string[]>([ASKS[0]]);
  const first = letter.name.split(" ")[0];

  if (!letter.permissions.findPeople) {
    return <span className="stamp">{first} is not taking introductions right now</span>;
  }

  return (
    <>
      <button className="btn" onClick={() => setOpen(true)}>
        Say hello
      </button>
      {open && (
        <div className="dialog" role="dialog" aria-modal="true" aria-label={`Say hello to ${first}`}>
          <div className="paper stack">
            {!sent ? (
              <>
                <h2 className="h2">Say hello to {first}.</h2>
                <p className="dim">
                  {first}&apos;s agent will carry this to {first}, who decides. You will not see contact details until they say yes.
                </p>
                <label className="field">
                  <span className="k">Who you are</span>
                  <input id="hello-who" className="fill wide" value={who} onChange={(e) => setWho(e.target.value)} placeholder="Your name, and one line about you" />
                </label>
                <label className="field">
                  <span className="k">Why {first}, why now</span>
                  <textarea id="hello-why" value={why} onChange={(e) => setWhy(e.target.value)} placeholder="Two or three honest sentences work best." />
                </label>
                <div className="stack" style={{ gap: 8 }}>
                  <span className="m dim">What you are asking for</span>
                  <div className="row">
                    {ASKS.map((a) => {
                      const on = asks.includes(a);
                      return (
                        <button key={a} type="button" className={`tap${on ? " on" : ""}`} aria-pressed={on} onClick={() => setAsks(on ? asks.filter((x) => x !== a) : [...asks, a])}>
                          {a}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div className="row">
                  <button className="btn" disabled={!who.trim() || !why.trim() || asks.length === 0} onClick={() => setSent(true)}>
                    Send to {first}&apos;s agent
                  </button>
                  <button className="btn quiet" onClick={() => setOpen(false)}>
                    Not now
                  </button>
                </div>
                <p className="m dim">You can send three hellos a day. Your agent can send one for you if you have a letter.</p>
              </>
            ) : (
              <>
                <h2 className="h2">Sent. {first} decides.</h2>
                <AgentNote label={`${first}'s agent`}>
                  <div>
                    I have your note and I am asking {first} now. People usually answer within two days. If it is a yes, I will suggest times that work for
                    both of you.
                  </div>
                </AgentNote>
                <div className="row">
                  <span className="stamp agent">waiting for {first}</span>
                  <button className="btn quiet" onClick={() => setOpen(false)}>
                    Close
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

/**
 * "Ask this letter": replaces the old chat widget that answered in first
 * person as the owner and was told never to say it was an AI (slice S14).
 * This one is labelled as the agent, answers only from inked lines, says when
 * the letter does not cover something, and offers the hello instead.
 */
export function AskLetter({ letter }: { letter: Letter }) {
  const [q, setQ] = useState("");
  const [log, setLog] = useState<{ q: string; a: string }[]>([]);
  const first = letter.name.split(" ")[0];
  const inked = letter.facts.filter((f) => f.state === "ink");
  const examples = [`What is ${first} building?`, `What is ${first} looking for?`, `Does ${first} do consulting?`];

  function answer(question: string) {
    const words = question.toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length > 3);
    const kinds = { build: "building", look: "looking_for", help: "can_help", ship: "shipped" } as const;
    let hits = inked.filter((f) => Object.entries(kinds).some(([k, kind]) => question.toLowerCase().includes(k) && f.kind === kind));
    if (!hits.length) hits = inked.filter((f) => words.some((w) => f.text.toLowerCase().includes(w)));
    const a = hits.length
      ? hits.map((f) => `${KIND_LABEL[f.kind]}: ${f.text}.`).join(" ")
      : `${first}'s letter does not say. I will not guess. You can say hello and ask ${first} directly.`;
    setLog((l) => [...l, { q: question, a }]);
    setQ("");
  }

  return (
    <div className="stack">
      <AgentNote label={`${first}'s agent · an AI, answering only from this letter`}>
        {log.length === 0 && <div>Ask me about {first}. If the letter does not cover it, I will say so.</div>}
        {log.map((turn, i) => (
          <div key={i} className="stack" style={{ gap: 4 }}>
            <div style={{ opacity: 0.7 }}>&gt; {turn.q}</div>
            <div>{turn.a}</div>
          </div>
        ))}
      </AgentNote>
      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault();
          if (q.trim()) answer(q.trim());
        }}
      >
        <input id="ask-letter" value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Ask about ${first}…`} aria-label={`Ask about ${first}`} />
        <button className="btn small agent" type="submit">
          Ask
        </button>
      </form>
      <div className="chips">
        {examples.map((ex) => (
          <button key={ex} type="button" className="chip" onClick={() => answer(ex)}>
            {ex}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Unclaimed letters get two actions only: claim it, or have it removed. */
export function ClaimActions({ name }: { name: string }) {
  const [state, setState] = useState<"idle" | "claim" | "remove">("idle");
  const first = name.split(" ")[0];
  if (state === "claim") return <p className="mono glow">Sign in with the LinkedIn account this page was built from, and it is yours to write.</p>;
  if (state === "remove") return <p className="mono glow">Removal requested. This page is hidden while we check.</p>;
  return (
    <div className="row">
      <button className="btn" onClick={() => setState("claim")}>
        I am {first}: write my letter
      </button>
      <button className="btn quiet" onClick={() => setState("remove")}>
        This is me: remove it
      </button>
    </div>
  );
}
