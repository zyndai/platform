import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { FactLine, Footer, TopBar } from "@/components/dear/ui";
import { ageLabel, byKind, getLetter } from "@/lib/dear/repo";
import { AskLetter, ClaimActions, SayHello } from "./letter-actions";

type Props = { params: Promise<{ handle: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { handle } = await params;
  const letter = await getLetter(handle);
  return { title: letter ? letter.name : "Letter not found" };
}

/**
 * The public letter (slices S03, S06, S07, S12, S14).
 *
 * What changed from the current profile page, per the review:
 *  - one primary action ("Say hello") instead of none;
 *  - "what is true today" comes first, history last;
 *  - every line shows where it came from and when it was approved;
 *  - the assistant is labelled as an AI and answers only from inked lines;
 *  - unclaimed pages are trimmed, labelled, and offer claim or removal only.
 */
export default async function LetterPage({ params }: Props) {
  const { handle } = await params;
  const letter = await getLetter(handle);
  if (!letter) notFound();
  const first = letter.name.split(" ")[0];

  if (!letter.claimed) {
    return (
      <div className="shell narrow">
        <TopBar />
        <div className="panel stack-lg">
          <span className="stamp warn" style={{ alignSelf: "flex-start" }}>
            no letter yet · built from public data
          </span>
          <h1 className="display" style={{ fontSize: "clamp(40px, 7vw, 60px)" }}>
            {letter.name}
          </h1>
          <p className="lede">
            {letter.headline} · {letter.location}
          </p>
          <p className="dim">
            {first} has not written a letter. This page is not shown to AI agents or search engines, has no assistant, and takes no introductions. If you
            know {first}, you can invite them to write one.
          </p>
          <ClaimActions name={letter.name} />
          <div className="row">
            <button className="btn small quiet">Invite {first} to write theirs</button>
          </div>
        </div>
        <Footer />
      </div>
    );
  }

  const building = byKind(letter, "building");
  const looking = byKind(letter, "looking_for");
  const help = byKind(letter, "can_help");
  const shipped = byKind(letter, "shipped");
  const background = [...byKind(letter, "role"), ...byKind(letter, "location"), ...byKind(letter, "skill")];

  return (
    <div className="shell">
      <TopBar />

      <div className="cols">
        <article className="paper stack-lg">
          <header className="stack">
            <p className="m dim">A letter to the agents · updated {ageLabel(letter.updatedAt)}</p>
            <h1 className="display" style={{ fontSize: "clamp(44px, 7vw, 68px)" }}>
              {letter.name}
            </h1>
            <p style={{ fontSize: 24 }} className="dim">
              {letter.headline} · {letter.location}
            </p>
            <div className="row">
              <SayHello letter={letter} />
              <span className="m dim">Ask for an introduction · {first} decides</span>
            </div>
            <p className="mono" style={{ color: "var(--agent)" }}>
              ↳ This is {first}&apos;s letter to the agents: what {first} says is true today. Every line is dated and approved by {first}, and AI can read it.
            </p>
          </header>

          <section className="stack">
            <hr />
            <p className="m dim">Here is what&apos;s true today</p>
            {building.length > 0 && (
              <div>
                <p className="m" style={{ color: "var(--agent)" }}>
                  What I&apos;m building
                </p>
                <ul className="facts">{building.map((f) => <FactLine key={f.id} fact={f} />)}</ul>
              </div>
            )}
            {looking.length > 0 && (
              <div>
                <p className="m" style={{ color: "var(--agent)" }}>
                  What I&apos;m looking for
                </p>
                <ul className="facts">{looking.map((f) => <FactLine key={f.id} fact={f} />)}</ul>
              </div>
            )}
            {help.length > 0 && (
              <div>
                <p className="m" style={{ color: "var(--agent)" }}>
                  Who I can help
                </p>
                <ul className="facts">{help.map((f) => <FactLine key={f.id} fact={f} />)}</ul>
              </div>
            )}
          </section>

          {shipped.length > 0 && (
            <section className="stack">
              <hr />
              <p className="m dim">Shipped lately</p>
              <ul className="facts">{shipped.map((f) => <FactLine key={f.id} fact={f} />)}</ul>
            </section>
          )}

          <section className="stack">
            <hr />
            <p className="m dim">What my agent may do</p>
            <div className="row">
              <span className={`stamp ${letter.permissions.speakForMe ? "ok" : ""}`}>{letter.permissions.speakForMe ? "✓" : "✕"} speak for me</span>
              <span className={`stamp ${letter.permissions.findPeople ? "ok" : ""}`}>{letter.permissions.findPeople ? "✓" : "✕"} find the right people</span>
              <span className={`stamp ${letter.permissions.hireAgents ? "ok" : ""}`}>{letter.permissions.hireAgents ? "✓" : "✕"} put agents to work</span>
            </div>
            <p style={{ fontSize: 26 }}>
              But before it promises anything in my name, <em className="ask it">it asks me first.</em>
            </p>
          </section>

          <section className="stack">
            <hr />
            <p className="m dim">Background</p>
            <ul className="facts">{background.map((f) => <FactLine key={f.id} fact={f} />)}</ul>
            {letter.history.length > 0 && (
              <dl className="kv" style={{ marginTop: 6 }}>
                {letter.history.map((h) => (
                  <div key={h.org} style={{ display: "contents" }}>
                    <dt>
                      {h.from}–{h.to ?? "now"}
                    </dt>
                    <dd>
                      {h.role}, {h.org}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </section>

          <p className="it" style={{ fontSize: 30 }}>
            Yours, {first}.
          </p>
          {letter.signedAt && <span className="stamp ok" style={{ alignSelf: "flex-start" }}>signed {ageLabel(letter.signedAt)} · every line approved by {first}</span>}
        </article>

        <aside className="stack-lg">
          <div className="panel stack">
            <h2 className="h3">Ask this letter</h2>
            <AskLetter letter={letter} />
          </div>

          <div className="panel stack">
            <h2 className="h3">For agents</h2>
            <dl className="kv">
              <dt>Agent</dt>
              <dd className="mono">{letter.agentId}</dd>
              <dt>Read</dt>
              <dd className="mono">/dear/l/{letter.handle}/data.json</dd>
              <dt>Cite as</dt>
              <dd className="mono">
                {letter.name}, Dear Agent, as of {letter.updatedAt}
              </dd>
              <dt>Act</dt>
              <dd className="mono">say_hello · needs {first}&apos;s approval</dd>
            </dl>
            <Link href="/dear/for-agents" className="chip" style={{ alignSelf: "flex-start" }}>
              How agents read a letter
            </Link>
          </div>

          <div className="panel stack">
            <h2 className="h3">Want one?</h2>
            <p className="dim">One link that tells every AI, and every person, who you are today. Free, about two minutes.</p>
            <Link href="/dear/write" className="btn agent" style={{ alignSelf: "flex-start" }}>
              Write your letter
            </Link>
          </div>
        </aside>
      </div>

      <Footer />
    </div>
  );
}
