import type { Metadata } from "next";
import Link from "next/link";
import { AgentNote, Footer, TopBar } from "@/components/dear/ui";
import { ageLabel, byKind, expiresIn, getActivity, getIntros, getMyLetter, getPencilled, getSources } from "@/lib/dear/repo";

export const metadata: Metadata = { title: "Your desk" };

/**
 * Owner home, "your desk" (slice S10). It answers the one question the current
 * edit form cannot: is my letter working? Who asked, what they asked, what my
 * agent could not answer, and the two or three things worth doing today.
 */
export default async function Home() {
  const [letter, pencilled, intros, activity, sources] = await Promise.all([getMyLetter(), getPencilled(), getIntros(), getActivity(), getSources()]);
  const first = letter.name.split(" ")[0];
  const waiting = intros.filter((i) => i.status === "waiting");
  const looking = byKind(letter, "looking_for")[0];
  const left = looking ? expiresIn(looking) : null;
  const unanswered = activity.asks.filter((a) => !a.answered);
  const inked = letter.facts.filter((f) => f.state === "ink").length;
  const fresh = letter.facts.filter((f) => f.state === "ink" && Date.parse(f.approvedAt ?? f.asOf) > Date.parse("2026-09-08")).length;

  return (
    <div className="shell">
      <TopBar owner current="/dear/home" inbox={pencilled.length + waiting.length} />

      <header className="stack">
        <p className="m glow">Your desk · week of {new Date(activity.weekOf).toLocaleDateString("en-GB", { day: "numeric", month: "long", timeZone: "UTC" })}</p>
        <h1 className="display" style={{ fontSize: "clamp(40px, 6vw, 64px)" }}>
          Good evening, {first}.
        </h1>
        <p className="lede">
          {activity.agentAsks} agents asked about you this week. {waiting.length} {waiting.length === 1 ? "person wants" : "people want"} to say hello.
        </p>
      </header>

      <div className="grid3">
        <div className="panel stack">
          <span className="num">{activity.agentAsks}</span>
          <span className="m glow">Found by AI</span>
          <span className="dim">times an AI asked about you this week</span>
        </div>
        <div className="panel stack">
          <span className="num">{activity.views}</span>
          <span className="m glow">Your one link</span>
          <span className="dim">people opened your letter</span>
        </div>
        <div className="panel stack">
          <span className="num">{activity.introsAccepted}</span>
          <span className="m glow">The right people</span>
          <span className="dim">hello accepted, {waiting.length} waiting for you</span>
        </div>
      </div>

      <div className="cols">
        <section className="paper stack-lg">
          <div className="stack">
            <h2 className="h2">Worth doing today</h2>
            <div className="rows">
              {waiting.length > 0 && (
                <div className="row between">
                  <span style={{ fontSize: 23 }}>
                    {waiting[0].from.name}
                    {waiting.length > 1 ? ` and ${waiting.length - 1} other` : ""} would like to say hello.
                  </span>
                  <Link href="/dear/inbox" className="btn small">
                    Decide
                  </Link>
                </div>
              )}
              <div className="row between">
                <span style={{ fontSize: 23 }}>Your agent pencilled in {pencilled.length} lines. Two look right.</span>
                <Link href="/dear/inbox" className="btn small">
                  Review
                </Link>
              </div>
              {looking && left !== null && (
                <div className="row between">
                  <span style={{ fontSize: 23 }}>
                    “{looking.text}” <span className={left < 10 ? "stale" : "dim"}>{left >= 0 ? `expires in ${left} days.` : "has expired."}</span>
                  </span>
                  <button className="btn small quiet">Still looking</button>
                </div>
              )}
            </div>
          </div>

          <div className="stack">
            <hr />
            <h2 className="h2">Who asked, and what</h2>
            <div className="rows">
              {activity.asks.map((a) => (
                <div key={a.id} className="stack" style={{ gap: 4 }}>
                  <span style={{ fontSize: 23 }}>“{a.question}”</span>
                  <span className="row" style={{ gap: 10 }}>
                    <span className="m dim">
                      {a.who} · {ageLabel(a.at)}
                    </span>
                    {a.answered ? <span className="stamp ok">answered from your letter</span> : <span className="stamp warn">your letter does not say</span>}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <aside className="stack-lg">
          <div className="panel stack">
            <h2 className="h3">What your agent could not answer</h2>
            <AgentNote>
              <div>
                {unanswered.length} people asked whether you take advisory or consulting work. Your letter does not say, so I told them I would not guess.
                Want to add a line?
              </div>
              <div className="row">
                <Link href="/dear/l/meera-iyer" className="btn small agent">
                  Add a line
                </Link>
              </div>
            </AgentNote>
          </div>

          <div className="panel stack">
            <h2 className="h3">Letter health</h2>
            <dl className="kv">
              <dt>In ink</dt>
              <dd>{inked} lines</dd>
              <dt>Fresh</dt>
              <dd>
                {fresh} of {inked} approved in the last 30 days
              </dd>
              <dt>Sources</dt>
              <dd>
                {sources.filter((s) => s.connected).length} connected ·{" "}
                <Link href="/dear/sources" className="glow">
                  manage
                </Link>
              </dd>
              <dt>Last signed</dt>
              <dd>{letter.signedAt ? ageLabel(letter.signedAt) : "not yet"}</dd>
            </dl>
          </div>

          <div className="panel stack">
            <h2 className="h3">See it as others do</h2>
            <div className="row">
              <Link href="/dear/l/meera-iyer" className="btn small quiet">
                As a person
              </Link>
              <Link href="/dear/for-agents" className="btn small quiet">
                As an agent
              </Link>
              <Link href="/dear/share" className="btn small quiet">
                Share it
              </Link>
            </div>
          </div>
        </aside>
      </div>

      <Footer />
    </div>
  );
}
