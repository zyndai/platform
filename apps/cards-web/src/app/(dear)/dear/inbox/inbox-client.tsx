"use client";

import { useState } from "react";
import { AgentNote, Legend, Receipt } from "@/components/dear/ui";
import { ageLabel, KIND_LABEL } from "@/lib/dear/repo";
import type { Fact, FactKind, InkState, IntroRequest, Triage } from "@/lib/dear/types";

const GROUPS: { key: Triage; title: string; blurb: string }[] = [
  { key: "looks_right", title: "Looks right", blurb: "Matches what you have already said." },
  { key: "needs_look", title: "Needs a look", blurb: "Old, or I am not sure what it means." },
  { key: "noise", title: "Probably noise", blurb: "Repository names and one-off tasks. I would leave these out." },
];

const RETYPE: FactKind[] = ["building", "shipped", "can_help", "tool"];

/**
 * The inbox (slices S01, S02, S05, S12). The review's complaints about the
 * current queue, and what this does instead:
 *  - a flat list of twenty rows → three groups with bulk actions;
 *  - approving silently changed a fact's meaning → "shows as" is visible and
 *    can be changed before inking;
 *  - "keep private" items came back → strike is permanent and says so;
 *  - nothing confirmed the public page had updated → "live on your letter".
 * Hellos sit in the same inbox, because both are things only the owner decides.
 */
export function InboxClient({ pencilled, intros }: { pencilled: Fact[]; intros: IntroRequest[] }) {
  const [tab, setTab] = useState<"lines" | "hellos">("lines");
  const [state, setState] = useState<Record<string, InkState>>({});
  const [kind, setKind] = useState<Record<string, FactKind>>({});
  const [text, setText] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [own, setOwn] = useState<string[]>([]);
  const [ownDraft, setOwnDraft] = useState("");
  const [decided, setDecided] = useState<Partial<Record<string, "accepted" | "declined">>>({});

  const of = (f: Fact) => state[f.id] ?? "pencil";
  const left = pencilled.filter((f) => of(f) === "pencil").length;
  const waiting = intros.filter((i) => i.status === "waiting" && !decided[i.id]);

  /** Your own wording is approved the moment you save it. */
  function saveRewrite(id: string) {
    if (draft.trim()) {
      setText((t) => ({ ...t, [id]: draft.trim() }));
      setState((st) => ({ ...st, [id]: "ink" }));
    }
    setEditing(null);
  }

  function all(group: Triage, to: InkState) {
    setState((s) => ({ ...s, ...Object.fromEntries(pencilled.filter((f) => f.triage === group).map((f) => [f.id, to])) }));
  }

  return (
    <div className="stack-lg">
      <div className="row" role="tablist">
        <button role="tab" aria-selected={tab === "lines"} className={`btn small ${tab === "lines" ? "agent" : "quiet"}`} onClick={() => setTab("lines")}>
          In pencil · {left}
        </button>
        <button role="tab" aria-selected={tab === "hellos"} className={`btn small ${tab === "hellos" ? "agent" : "quiet"}`} onClick={() => setTab("hellos")}>
          Hellos · {waiting.length}
        </button>
      </div>

      {tab === "lines" && (
        <div className="paper stack-lg">
          <div className="stack">
            <h1 className="h2">Your agent pencilled these in.</h1>
            <p className="dim">Nothing here is public. Ink a line to add it to your letter. Strike it and it is never suggested or said again.</p>
            <Legend />
          </div>

          {GROUPS.map((g) => {
            const items = pencilled.filter((f) => f.triage === g.key);
            if (!items.length) return null;
            return (
              <section key={g.key} className="stack">
                <hr />
                <div className="row between">
                  <div>
                    <h2 className="h3">{g.title}</h2>
                    <p className="dim" style={{ fontSize: 17 }}>
                      {g.blurb}
                    </p>
                  </div>
                  {g.key === "noise" ? (
                    <button className="tap" onClick={() => all(g.key, "struck")}>
                      Strike all
                    </button>
                  ) : g.key === "looks_right" ? (
                    <button className="tap" onClick={() => all(g.key, "ink")}>
                      Ink all
                    </button>
                  ) : null}
                </div>
                <ul className="facts">
                  {items.map((f) => {
                    const st = of(f);
                    const k = kind[f.id] ?? f.kind;
                    return (
                      <li key={f.id} className={`fact ${st}`}>
                        <span className="t">
                          {editing === f.id ? (
                            <input
                              id={`inbox-rewrite-${f.id}`}
                              className="fill wide"
                              value={draft}
                              onChange={(e) => setDraft(e.target.value)}
                              onKeyDown={(e) => e.key === "Enter" && saveRewrite(f.id)}
                              aria-label="Rewrite this line in your own words"
                              autoFocus
                            />
                          ) : (
                            text[f.id] ?? f.text
                          )}
                        </span>
                        <span className="stack" style={{ gap: 4, gridColumn: 1 }}>
                          {st === "pencil" ? <Receipt fact={f} /> : <span className="src">{st === "ink" ? `${text[f.id] ? "written by you · " : ""}approved just now · live on your letter` : "struck · will never be said"}</span>}
                          {st === "pencil" && f.note && <span className="mono" style={{ color: "var(--agent)" }}>↳ {f.note}</span>}
                          {st !== "struck" && (
                            <span className="row" style={{ gap: 6 }}>
                              <span className="m dim">shows as</span>
                              {RETYPE.map((opt) => (
                                <button key={opt} type="button" className={`tap${k === opt ? " on" : ""}`} disabled={st === "ink"} onClick={() => setKind({ ...kind, [f.id]: opt })}>
                                  {KIND_LABEL[opt]}
                                </button>
                              ))}
                            </span>
                          )}
                        </span>
                        <span className="acts">
                          <button type="button" className={`tap${st === "ink" ? " on" : ""}`} onClick={() => setState({ ...state, [f.id]: "ink" })}>
                            Ink it
                          </button>
                          {editing === f.id ? (
                            <button type="button" className="tap on" onClick={() => saveRewrite(f.id)}>
                              Save
                            </button>
                          ) : (
                            <button
                              type="button"
                              className="tap"
                              onClick={() => {
                                setEditing(f.id);
                                setDraft(text[f.id] ?? f.text);
                              }}
                            >
                              Rewrite
                            </button>
                          )}
                          <button type="button" className={`tap${st === "struck" ? " on" : ""}`} onClick={() => setState({ ...state, [f.id]: "struck" })}>
                            Strike
                          </button>
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}

          <section className="stack">
            <hr />
            <h2 className="h3">Something I missed?</h2>
            {own.length > 0 && (
              <ul className="facts">
                {own.map((line, i) => (
                  <li key={i} className="fact ink">
                    <span className="t">{line}</span>
                    <span className="src">written by you · live on your letter</span>
                  </li>
                ))}
              </ul>
            )}
            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault();
                if (ownDraft.trim()) setOwn([...own, ownDraft.trim()]);
                setOwnDraft("");
              }}
            >
              <input id="inbox-own" className="fill" style={{ flex: "1 1 260px", fontSize: 23 }} value={ownDraft} onChange={(e) => setOwnDraft(e.target.value)} placeholder="Add a line of your own…" aria-label="Add a line of your own" autoComplete="off" />
              <button className="tap" type="submit" disabled={!ownDraft.trim()}>
                Add
              </button>
            </form>
            <p className="m dim">What you type yourself goes straight to ink</p>
          </section>

          {left === 0 && <span className="stamp ok" style={{ alignSelf: "flex-start" }}>inbox clear · your letter is up to date</span>}
        </div>
      )}

      {tab === "hellos" && (
        <div className="stack-lg">
          {intros.map((i) => {
            const status: IntroRequest["status"] = decided[i.id] ?? i.status;
            return (
              <article key={i.id} className="paper stack">
                <div className="row between">
                  <h2 className="h3">
                    {i.from.name} <span className="dim">· {i.from.headline}</span>
                  </h2>
                  <span className={`stamp ${status === "accepted" ? "ok" : status === "declined" ? "" : "agent"}`}>
                    {status === "waiting" ? `${i.from.via === "agent" ? "sent by their agent" : "sent by them"} · ${ageLabel(i.at)}` : status}
                  </span>
                </div>
                <p style={{ fontSize: 23 }}>“{i.why}”</p>
                {i.matched && (
                  <p className="mono" style={{ color: "var(--agent)" }}>
                    ↳ matched your line: {i.matched}
                  </p>
                )}
                <p className="m dim">They are asking for: {i.asks.join(" · ")}</p>
                {status === "waiting" ? (
                  <div className="row">
                    <button className="btn" onClick={() => setDecided({ ...decided, [i.id]: "accepted" })}>
                      Yes, say hello back
                    </button>
                    <button className="btn quiet" onClick={() => setDecided({ ...decided, [i.id]: "declined" })}>
                      Not now
                    </button>
                    <span className="m dim">They see nothing until you answer</span>
                  </div>
                ) : status === "accepted" ? (
                  <AgentNote>
                    <div>Done. I have shared your email with {i.from.name.split(" ")[0]} and offered three times that work for you both.</div>
                  </AgentNote>
                ) : (
                  <p className="m dim">Declined quietly. {i.from.name.split(" ")[0]} was told you are not available right now.</p>
                )}
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
