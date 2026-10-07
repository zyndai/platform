"use client";

import Link from "next/link";
import { useState } from "react";
import { AgentNote, Legend } from "@/components/dear/ui";
import { ageLabel, KIND_LABEL, SOURCE_LABEL } from "@/lib/dear/repo";
import type { Fact, FactKind, Letter } from "@/lib/dear/types";

const SECTIONS: { title: string; kinds: FactKind[] }[] = [
  { title: "Here is what's true today", kinds: ["building", "looking_for", "can_help"] },
  { title: "Shipped lately", kinds: ["shipped"] },
  { title: "Background", kinds: ["role", "location", "skill"] },
];

const PLACEHOLDER: Record<FactKind, string> = {
  building: "Something else you are building…",
  looking_for: "Something else you are looking for…",
  can_help: "Something else you can help with…",
  shipped: "Something you shipped…",
  role: "What you do, in your words…",
  location: "Where you are based…",
  skill: "What you work with…",
  tool: "A tool you use…",
};

/**
 * Edit my letter. The owner can change any line at any time, not only when
 * the agent suggests one: double-click a line (or press Rewrite) to reword it,
 * add a line to any section, strike a line, or restore a struck one.
 * Whatever the owner types is ink at once and marked "written by you".
 */
export function LetterEditor({ letter }: { letter: Letter }) {
  const [facts, setFacts] = useState<Fact[]>(letter.facts.filter((f) => f.state !== "pencil"));
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [adds, setAdds] = useState<Partial<Record<FactKind, string>>>({});
  const [saved, setSaved] = useState<string | null>(null);

  const patch = (id: string, change: Partial<Fact>) => setFacts((cur) => cur.map((f) => (f.id === id ? { ...f, ...change } : f)));

  function begin(f: Fact) {
    setEditing(f.id);
    setDraft(f.text);
  }

  function save(id: string) {
    const text = draft.trim();
    if (text) {
      patch(id, { text, source: "you", state: "ink", approvedAt: "2026-10-08", asOf: "2026-10-08", alsoIn: undefined });
      setSaved(id);
    }
    setEditing(null);
  }

  function add(kind: FactKind) {
    const text = (adds[kind] ?? "").trim();
    if (!text) return;
    const id = `own-${kind}-${facts.length}`;
    setFacts((cur) => [...cur, { id, kind, text, source: "you", asOf: "2026-10-08", approvedAt: "2026-10-08", state: "ink" }]);
    setAdds({ ...adds, [kind]: "" });
    setSaved(id);
  }

  const line = (f: Fact) =>
    editing === f.id ? (
      <li key={f.id} className="fact ink">
        <span className="t">
          <input
            id={`edit-${f.id}`}
            className="fill wide"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") save(f.id);
              if (e.key === "Escape") setEditing(null);
            }}
            aria-label="Rewrite this line"
            autoFocus
          />
        </span>
        <span className="src">enter to save · escape to cancel</span>
        <span className="acts">
          <button type="button" className="tap on" onClick={() => save(f.id)}>
            Save
          </button>
          <button type="button" className="tap" onClick={() => setEditing(null)}>
            Cancel
          </button>
        </span>
      </li>
    ) : (
      <li key={f.id} className={`fact ${f.state}`}>
        <span className="t" onDoubleClick={() => f.state === "ink" && begin(f)} title={f.state === "ink" ? "Double-click to rewrite" : undefined} style={{ cursor: f.state === "ink" ? "text" : undefined }}>
          {f.text}
        </span>
        <span className="src">
          {f.state === "struck"
            ? "struck · will never be said"
            : `${f.source === "you" ? "Written by you" : SOURCE_LABEL[f.source]} · approved ${ageLabel(f.approvedAt ?? f.asOf)}${saved === f.id ? " · saved · live on your letter" : ""}`}
        </span>
        <span className="acts">
          {f.state === "ink" ? (
            <>
              <button type="button" className="tap" onClick={() => begin(f)}>
                Rewrite
              </button>
              <button type="button" className="tap" onClick={() => patch(f.id, { state: "struck" })}>
                Strike
              </button>
            </>
          ) : (
            <button type="button" className="tap" onClick={() => patch(f.id, { state: "ink", approvedAt: "2026-10-08" })}>
              Restore
            </button>
          )}
        </span>
      </li>
    );

  const struck = facts.filter((f) => f.state === "struck");

  return (
    <div className="stack-lg">
      <header className="stack">
        <h1 className="display" style={{ fontSize: "clamp(40px, 6vw, 60px)" }}>
          Your letter, in your words.
        </h1>
        <p className="lede">Double-click any line to rewrite it. Add a line anywhere. You never have to wait for your agent to suggest something.</p>
        <div className="row">
          <Link href={`/dear/l/${letter.handle}`} className="btn small quiet">
            See it as a visitor
          </Link>
          <Link href="/dear/inbox" className="btn small quiet">
            Review what your agent suggested
          </Link>
        </div>
      </header>

      <div className="paper stack-lg">
        <Legend />
        {SECTIONS.map((section) => (
          <section key={section.title} className="stack">
            <hr />
            <p className="m dim">{section.title}</p>
            {section.kinds.map((kind) => (
              <div key={kind} className="stack" style={{ gap: 4 }}>
                <p className="m" style={{ color: "var(--agent)" }}>
                  {KIND_LABEL[kind]}
                </p>
                <ul className="facts">{facts.filter((f) => f.kind === kind && f.state === "ink").map(line)}</ul>
                <form
                  className="row"
                  onSubmit={(e) => {
                    e.preventDefault();
                    add(kind);
                  }}
                >
                  <input id={`add-${kind}`} className="fill" style={{ flex: "1 1 260px", fontSize: 21 }} value={adds[kind] ?? ""} onChange={(e) => setAdds({ ...adds, [kind]: e.target.value })} placeholder={PLACEHOLDER[kind]} aria-label={`Add a line: ${KIND_LABEL[kind]}`} autoComplete="off" />
                  <button className="tap" type="submit" disabled={!(adds[kind] ?? "").trim()}>
                    Add
                  </button>
                </form>
              </div>
            ))}
          </section>
        ))}

        {struck.length > 0 && (
          <section className="stack">
            <hr />
            <p className="m dim">Never say this</p>
            <ul className="facts">{struck.map(line)}</ul>
          </section>
        )}
      </div>

      <AgentNote>
        <div>When you write a line yourself I take it as true and say it from now on. I will still tell you if something I find elsewhere disagrees with it.</div>
      </AgentNote>
    </div>
  );
}
