"use client";

import Link from "next/link";
import { useState } from "react";
import { AgentNote, CraneLit, Legend } from "@/components/dear/ui";
import type { InkState, SourceId } from "@/lib/dear/types";

/**
 * Onboarding as a letter (engineering guide slice S08).
 *
 * The user never meets a "connect your accounts" screen. Each source arrives
 * as the next line of the letter, asked for by the agent:
 *   name → LinkedIn (ink or strike each line) → what's true today (GitHub and
 *   X pencil in the blanks) → permissions → sign → P.S. connect an assistant →
 *   ask it who you are.
 * No account is needed until the first connection or the signature.
 *
 * A person can always use their own words: every suggested line has "Rewrite",
 * every section has "add a line of your own", and skipping LinkedIn opens
 * typed fields for role and place. Anything typed is ink at once, because
 * they wrote it.
 *
 * All imported lines below are examples; wire them to cards-api /onboard.
 */

type Found = { id: string; text: string; from: string; stale?: boolean; state: InkState };

const LINKEDIN: Found[] = [
  { id: "l1", text: "Founder at Lantern Labs", from: "LinkedIn · since 2024", state: "pencil" },
  { id: "l2", text: "Backend engineer at a company I left", from: "LinkedIn · last updated 2021 · still true?", stale: true, state: "pencil" },
  { id: "l3", text: "Open to work", from: "LinkedIn · set in 2023 · still true?", stale: true, state: "pencil" },
  { id: "l4", text: "Based in Bengaluru", from: "LinkedIn", state: "pencil" },
];

const SUGGEST: Record<"github" | "x", Found & { field: "build" | "help"; value: string }> = {
  github: { id: "g1", text: "Building: an identity card that AI agents can read", from: "GitHub · 41 commits this month", state: "pencil", field: "build", value: "An identity card that AI agents can read" },
  x: { id: "x1", text: "Can help with: agent protocols and MCP", from: "X · 12 recent posts", state: "pencil", field: "help", value: "Agent protocols and MCP" },
};

const ASSISTANTS = ["Claude", "Cursor", "ChatGPT"] as const;

function lower(s: string) {
  const t = s.trim().replace(/\.$/, "");
  return t.charAt(0).toLowerCase() + t.slice(1);
}

export function WriteClient() {
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [linkedin, setLinkedin] = useState<Found[] | null>(null);
  const [found, setFound] = useState<Found[]>([]);
  const [sources, setSources] = useState<SourceId[]>([]);
  const [today, setToday] = useState({ build: "", look: "", help: "" });
  const [perm, setPerm] = useState({ speak: true, people: true, agents: false });
  const [signed, setSigned] = useState(false);
  const [assistant, setAssistant] = useState<string | null>(null);
  const [noteInked, setNoteInked] = useState(false);
  const [answer, setAnswer] = useState<string | null>(null);
  const [own, setOwn] = useState<Found[]>([]);
  const [ownDraft, setOwnDraft] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [selfWrite, setSelfWrite] = useState(false);
  const [self, setSelf] = useState({ role: "", place: "" });

  const pct = signed ? 100 : { 1: 10, 2: 30, 3: 55, 4: 75, 5: 90 }[step] ?? 10;
  const liDecided = linkedin?.every((f) => f.state !== "pencil") ?? false;
  const anyToday = Boolean(today.build.trim() || today.look.trim() || today.help.trim());
  const everyLine = [...(linkedin ?? []), ...found, ...own];
  const inkCount = everyLine.filter((f) => f.state === "ink").length + Object.values(today).filter((v) => v.trim()).length;
  const struckCount = everyLine.filter((f) => f.state === "struck").length;
  const handle = (name || "you").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

  type Which = "li" | "found" | "own";

  function update(list: Which, id: string, patch: Partial<Found>) {
    const apply = (cur: Found[]) => cur.map((f) => (f.id === id ? { ...f, ...patch } : f));
    if (list === "li") setLinkedin((cur) => (cur ? apply(cur) : cur));
    else if (list === "found") setFound(apply);
    else setOwn(apply);
  }

  function mark(list: Which, id: string, state: InkState) {
    update(list, id, { state });
    const s = Object.values(SUGGEST).find((x) => x.id === id);
    if (list === "found" && s && state === "ink") setToday((t) => (t[s.field] ? t : { ...t, [s.field]: s.value }));
  }

  /** Saving your own wording approves it: you wrote it. */
  function saveRewrite(list: Which, id: string) {
    const text = draft.trim();
    if (text) update(list, id, { text, state: "ink", from: "Written by you", stale: false });
    setEditing(null);
  }

  function addOwn(text: string) {
    const t = text.trim();
    if (!t) return;
    setOwn((cur) => [...cur, { id: `o${cur.length + 1}`, text: t, from: "Written by you", state: "ink" }]);
  }

  function read(key: "github" | "x") {
    if (sources.includes(key)) return;
    setSources((s) => [...s, key]);
    setFound((f) => [...f, SUGGEST[key]]);
  }

  function ask() {
    const inked = [...(linkedin ?? []), ...own].filter((f) => f.state === "ink").map((f) => lower(f.text));
    let s = name || "This person";
    s += inked.length ? `: ${inked.join(", ")}.` : ".";
    if (today.build) s += ` Right now they are building ${lower(today.build)}.`;
    if (today.look) s += ` They are looking for ${lower(today.look)}.`;
    if (today.help) s += ` They can help with ${lower(today.help)}.`;
    if (noteInked) s += " This week they shipped intro requests.";
    s += perm.people ? " I can introduce you, and I will ask them first." : " They have not allowed introductions yet.";
    setAnswer(s);
  }

  const rows = (list: Found[], which: Which) => (
    <ul className="facts">
      {list.map((f) =>
        editing === f.id ? (
          <li key={f.id} className="fact ink">
            <span className="t">
              <input
                id={`rewrite-${f.id}`}
                className="fill wide"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && saveRewrite(which, f.id)}
                aria-label="Rewrite this line in your own words"
                autoFocus
              />
            </span>
            <span className="src">your words go straight to ink</span>
            <span className="acts">
              <button type="button" className="tap on" onClick={() => saveRewrite(which, f.id)}>
                Save
              </button>
              <button type="button" className="tap" onClick={() => setEditing(null)}>
                Cancel
              </button>
            </span>
          </li>
        ) : (
          <li key={f.id} className={`fact ${f.state}`}>
            <span
              className="t"
              title="Double-click to rewrite"
              style={{ cursor: "text" }}
              onDoubleClick={() => {
                setEditing(f.id);
                setDraft(f.text);
              }}
            >
              {f.text}
            </span>
            <span className={`src${f.stale && f.state === "pencil" ? " stale" : ""}`}>
              {f.state === "ink" ? `${f.from.split(" · ")[0]} · approved today` : f.state === "struck" ? "struck · will never be said" : f.from}
            </span>
            <span className="acts">
              <button type="button" className={`tap${f.state === "ink" ? " on" : ""}`} onClick={() => mark(which, f.id, "ink")}>
                Ink it
              </button>
              <button
                type="button"
                className="tap"
                onClick={() => {
                  setEditing(f.id);
                  setDraft(f.text);
                }}
              >
                Rewrite
              </button>
              <button type="button" className={`tap${f.state === "struck" ? " on" : ""}`} onClick={() => mark(which, f.id, "struck")}>
                Strike
              </button>
            </span>
          </li>
        ),
      )}
    </ul>
  );

  const adder = (
    <form
      className="row"
      onSubmit={(e) => {
        e.preventDefault();
        addOwn(ownDraft);
        setOwnDraft("");
      }}
    >
      <input
        id="write-own"
        className="fill"
        style={{ flex: "1 1 260px", fontSize: 23 }}
        value={ownDraft}
        onChange={(e) => setOwnDraft(e.target.value)}
        placeholder="Add a line of your own…"
        aria-label="Add a line of your own"
        autoComplete="off"
      />
      <button className="tap" type="submit" disabled={!ownDraft.trim()}>
        Add
      </button>
    </form>
  );

  return (
    <div className="stack-lg">
      <div className="row between">
        <span className="m dim">{signed ? "Letter sent" : `Letter ${pct}% written`}</span>
        <span className="banner">example data · nothing is saved</span>
      </div>

      {!signed && (
        <div className="paper stack-lg">
          <section className="stack">
            <h1 className="display" style={{ fontSize: "clamp(40px, 8vw, 64px)" }}>
              Dear agent,
            </h1>
            <p style={{ fontSize: 25 }}>
              Someone is about to ask you about me. My name is{" "}
              <input id="write-name" className="fill" style={{ width: "11ch" }} value={name} onChange={(e) => setName(e.target.value)} placeholder="your name" aria-label="Your name" autoComplete="off" />.
            </p>
            {step === 1 && (
              <div className="row">
                <button className="btn" disabled={!name.trim()} onClick={() => setStep(2)}>
                  Keep writing
                </button>
              </div>
            )}
          </section>

          {step >= 2 && (
            <section className="stack rise">
              <hr />
              <p style={{ fontSize: 25 }}>So please, don&apos;t guess. And don&apos;t just read them my LinkedIn.</p>
              {!linkedin && !selfWrite && step === 2 && (
                <AgentNote>
                  <div>
                    I could guess from your LinkedIn. You just told me not to. Show it to me and <b>you</b> decide, line by line, what is still true.
                  </div>
                  <div className="row">
                    <button
                      className="btn small agent"
                      onClick={() => {
                        setLinkedin(LINKEDIN);
                        setSources((s) => [...s, "linkedin"]);
                      }}
                    >
                      Show my LinkedIn
                    </button>
                    <button className="btn small quiet" onClick={() => setSelfWrite(true)}>
                      I&apos;ll write it myself
                    </button>
                  </div>
                </AgentNote>
              )}
              {selfWrite && !linkedin && (
                <>
                  <label className="field">
                    <span className="k">What I do</span>
                    <input id="write-role" className="fill wide" value={self.role} onChange={(e) => setSelf({ ...self, role: e.target.value })} placeholder="Founder at…, designer, student of…" autoComplete="off" disabled={step > 2} />
                  </label>
                  <label className="field">
                    <span className="k">Where I&apos;m based</span>
                    <input id="write-place" className="fill wide" value={self.place} onChange={(e) => setSelf({ ...self, place: e.target.value })} placeholder="city, or “anywhere”" autoComplete="off" disabled={step > 2} />
                  </label>
                  {own.length > 0 && rows(own, "own")}
                  {adder}
                  {step === 2 && (
                    <div className="row">
                      <button
                        className="btn"
                        disabled={!self.role.trim()}
                        onClick={() => {
                          addOwn(self.role);
                          if (self.place.trim()) addOwn(`Based in ${self.place.trim()}`);
                          setStep(3);
                        }}
                      >
                        Keep writing
                      </button>
                      <button className="btn small quiet" onClick={() => setSelfWrite(false)}>
                        Show my LinkedIn instead
                      </button>
                    </div>
                  )}
                </>
              )}
              {linkedin && (
                <>
                  <Legend />
                  {rows(linkedin, "li")}
                  {own.length > 0 && rows(own, "own")}
                  {adder}
                  {step === 2 && (
                    <div className="row">
                      <button className="btn" disabled={!liDecided} onClick={() => setStep(3)}>
                        Keep writing
                      </button>
                      {!liDecided && <span className="m dim">Ink or strike each line first</span>}
                    </div>
                  )}
                </>
              )}
            </section>
          )}

          {step >= 3 && (
            <section className="stack rise">
              <hr />
              <p style={{ fontSize: 25 }}>Here is what&apos;s true today.</p>
              <label className="field">
                <span className="k">What I&apos;m building</span>
                <input id="write-build" className="fill wide" value={today.build} onChange={(e) => setToday({ ...today, build: e.target.value })} placeholder="in your own words" autoComplete="off" />
              </label>
              <label className="field">
                <span className="k">What I&apos;m looking for · expires in 30 days</span>
                <input id="write-look" className="fill wide" value={today.look} onChange={(e) => setToday({ ...today, look: e.target.value })} placeholder="a co-founder, a first customer, a review…" autoComplete="off" />
              </label>
              <label className="field">
                <span className="k">Who I can help</span>
                <input id="write-help" className="fill wide" value={today.help} onChange={(e) => setToday({ ...today, help: e.target.value })} placeholder="what people should bring you" autoComplete="off" />
              </label>
              <AgentNote>
                <div>Stuck on a blank line? I can pencil these in from what you ship and what you post. I only read; nothing is public until you ink it.</div>
                <div className="row">
                  <button className={`btn small agent${sources.includes("github") ? " done" : ""}`} disabled={sources.includes("github")} onClick={() => read("github")}>
                    {sources.includes("github") ? "GitHub read ✓" : "Read my GitHub"}
                  </button>
                  <button className={`btn small agent${sources.includes("x") ? " done" : ""}`} disabled={sources.includes("x")} onClick={() => read("x")}>
                    {sources.includes("x") ? "X read ✓" : "Read my X"}
                  </button>
                </div>
              </AgentNote>
              {found.length > 0 && rows(found, "found")}
              {step === 3 && (
                <div className="row">
                  <button className="btn" disabled={!anyToday} onClick={() => setStep(4)}>
                    Keep writing
                  </button>
                </div>
              )}
            </section>
          )}

          {step >= 4 && (
            <section className="stack rise">
              <hr />
              <div>
                {(
                  [
                    ["speak", "You can speak for me."],
                    ["people", "Find the right people."],
                    ["agents", "Put the right agents to work."],
                  ] as const
                ).map(([key, label]) => (
                  <button key={key} type="button" className="toggle" aria-pressed={perm[key]} onClick={() => setPerm({ ...perm, [key]: !perm[key] })}>
                    <span>{label}</span>
                    <span className="st">{perm[key] ? "✓ allowed" : "not yet"}</span>
                  </button>
                ))}
              </div>
              <p style={{ fontSize: "clamp(27px, 5vw, 36px)", lineHeight: 1.15 }}>
                But before you promise anything in my name, <em className="ask it">ask me first.</em>
              </p>
              <div className="row">
                <span className="stamp">always ask: introductions</span>
                <span className="stamp">always ask: meetings</span>
                <span className="stamp">always ask: anything that costs money</span>
              </div>
              {step === 4 && (
                <div className="row">
                  <button className="btn" onClick={() => setStep(5)}>
                    Keep writing
                  </button>
                </div>
              )}
            </section>
          )}

          {step >= 5 && (
            <section className="stack rise">
              <hr />
              <p className="it" style={{ fontSize: 36, lineHeight: 1.1 }}>
                Yours,
                <br />
                {name || "a human"}.
              </p>
              <div className="row">
                <button className="btn" onClick={() => setSigned(true)}>
                  Sign and send
                </button>
                <span className="m dim">Signing publishes only the lines in ink</span>
              </div>
            </section>
          )}
        </div>
      )}

      {signed && (
        <div className="stack-lg rise" style={{ alignItems: "center", textAlign: "center" }}>
          <CraneLit className="crane-hero" />
          <p className="mono glow" style={{ fontSize: 16, userSelect: "all" }}>
            dearagent.me/{handle}
          </p>
          <p className="m dim">
            {inkCount} lines in ink · {struckCount} struck · {sources.length} sources read
          </p>

          <div className="grid3" style={{ width: "100%", textAlign: "left" }}>
            <div className="panel stack">
              <span className="stamp ok" style={{ alignSelf: "flex-start" }}>✓ AI can read this</span>
              <p className="dim">When an AI is asked about you, your approved lines are there for it to find and quote.</p>
            </div>
            <div className="panel stack">
              <span className="stamp ok" style={{ alignSelf: "flex-start" }}>✓ This is your link</span>
              <p className="dim">Put it in your bio, your email signature and your GitHub profile.</p>
            </div>
            <div className="panel stack">
              <span className="stamp ok" style={{ alignSelf: "flex-start" }}>✓ You approve every hello</span>
              <p className="dim">People can ask for an introduction. Nothing is shared until you say yes.</p>
            </div>
          </div>

          <div className="panel stack" style={{ width: "100%", textAlign: "left" }}>
            <h2 className="h3">P.S. Keep me current.</h2>
            <AgentNote>
              <div>A letter goes stale. You work with an AI every day; let it tell me what you ship, as you ship it. I&apos;ll write it in pencil. You ink it, or you don&apos;t.</div>
              <div className="row">
                {ASSISTANTS.map((a) => (
                  <button key={a} className={`btn small agent${assistant === a ? " done" : ""}`} disabled={assistant !== null} onClick={() => setAssistant(a)}>
                    {assistant === a ? `${a} connected ✓` : `Connect ${a}`}
                  </button>
                ))}
              </div>
            </AgentNote>
            {assistant && (
              <div className="row between rise" style={{ border: "1px dashed var(--line)", borderRadius: 4, padding: "10px 12px" }}>
                <span className={noteInked ? "" : "it dim"} style={{ fontSize: 21 }}>
                  Shipped intro requests this week. <span className="m dim">from {assistant}, today</span>
                </span>
                <button className={`btn small quiet${noteInked ? " done" : ""}`} disabled={noteInked} onClick={() => setNoteInked(true)}>
                  {noteInked ? "In ink ✓" : "Ink it"}
                </button>
              </div>
            )}
          </div>

          <div className="panel stack" style={{ width: "100%", textAlign: "left" }}>
            <h2 className="h3">Now ask it who you are.</h2>
            <p className="dim">This is what an agent will say when someone asks about you. It can only use what you put in ink.</p>
            <div className="row">
              <button className="btn small agent" onClick={ask}>
                Who is this person?
              </button>
            </div>
            {answer && (
              <p className="rise" style={{ fontSize: 22, borderLeft: "2px solid var(--agent-glow)", paddingLeft: 14 }}>
                {answer}
              </p>
            )}
          </div>

          <div className="row">
            <Link href="/dear/share" className="btn">
              Share your letter
            </Link>
            <Link href="/dear/home" className="btn quiet">
              Go to your desk
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
