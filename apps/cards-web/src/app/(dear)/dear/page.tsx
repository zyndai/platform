import Link from "next/link";
import { AskBox } from "@/components/dear/ask-box";
import { AgentNote, Footer, Legend, TopBar } from "@/components/dear/ui";

/**
 * Landing page, written to the messaging framework: one line of imagination,
 * one line of use, then the three reasons people actually come ("doors").
 * A fresh visitor should know what they get before they scroll.
 */

const DOORS = [
  {
    tag: "Be found by AI",
    title: "Be the answer when an AI is asked for someone like you.",
    body: "People now ask ChatGPT and Claude for “a payments engineer in Hyderabad”. Your letter is written so an AI can read it, quote it, and get you right.",
    href: "#ask",
    cta: "See how an AI looks",
  },
  {
    tag: "One link, always current",
    title: "One link for who you are today.",
    body: "Put it where your link in bio, portfolio and stale profile go now. It starts from your LinkedIn in two minutes and suggests updates as you work.",
    href: "/dear/share",
    cta: "See the link",
  },
  {
    tag: "The right people",
    title: "Introductions, with your yes.",
    body: "When someone is looking for a person like you, your agent answers and brings you one request to approve. No cold messages, no contact details shared first.",
    href: "/dear/l/meera-iyer",
    cta: "See a letter",
  },
];

const BEATS = [
  {
    img: "/dear/desk.jpg",
    alt: "A blank sheet of paper on a desk under a lamp at night",
    title: "AI gets you right",
    body: "Say what you are building, what you are looking for and who you can help. Your agent suggests the rest from LinkedIn, GitHub and X. Every line carries a date.",
  },
  {
    img: "/dear/crane_desk.jpg",
    alt: "The letter folded into a paper crane, glowing on the desk",
    title: "You stay in control",
    body: "Nothing is public until you approve it. Your agent can speak for you and look for people, and before it promises anything in your name, it asks you first.",
  },
  {
    img: "/dear/two_cranes.jpg",
    alt: "Two paper cranes meeting on a wire at dawn",
    title: "The right people reach you",
    body: "You see who asked about you and what they asked. When it is a fit, you get a hello to accept or decline.",
  },
];

const QUESTIONS = [
  {
    q: "Is this Linktree?",
    a: "Linktree lists your links. This says who you are today, with a date on every line, and AI can read it. Use it as your one link if you like; most people do.",
  },
  {
    q: "Will this get me on ChatGPT?",
    a: "It makes sure that when an AI is asked about you, the truth is there for it to find and cite. Nobody can promise rankings, and we don't.",
  },
  {
    q: "Who sees what?",
    a: "Only what you approve. What your agent finds stays private until you say yes. Anything you block is never said.",
  },
  {
    q: "Why a letter?",
    a: "Because a profile is written to impress people, and a letter is written to be understood. Yours tells an AI what is true and what it may do in your name.",
  },
  {
    q: "What does it cost?",
    a: "Writing and sharing your letter is free.",
  },
];

export default function Landing() {
  return (
    <div className="shell">
      <TopBar />

      <section className="grid2">
        <div className="stack-lg">
          <p className="m glow">A letter to the agents</p>
          <h1 className="display">Your next collaborator won&apos;t Google you. Their agent will.</h1>
          <p className="lede">
            Dear Agent is one link that tells every AI, and every person, who you are today. You write it once, as a letter. It stays current.
          </p>
          <div className="row">
            <Link href="/dear/write" className="btn">
              Write your letter
            </Link>
            <a href="#film" className="btn quiet">
              Watch the film · 1:16
            </a>
          </div>
          <p className="m dim">Free · two minutes · replaces your link in bio</p>
        </div>

        <div className="paper tilt stack" aria-label="An example letter">
          <p style={{ fontSize: 44, lineHeight: 1 }}>Dear agent,</p>
          <p style={{ fontSize: 22 }}>Someone is about to ask you about me. So please, don&apos;t guess.</p>
          <p style={{ fontSize: 22 }}>
            Here is what&apos;s true today. I&apos;m building an identity card that AI agents can read. I&apos;m looking for a founding engineer.
          </p>
          <p style={{ fontSize: 22 }}>
            You can speak for me. But before you promise anything in my name, <em className="ask it">ask me first.</em>
          </p>
          <p className="it" style={{ fontSize: 26 }}>
            Yours, a human.
          </p>
          <span className="stamp ok" style={{ alignSelf: "flex-start" }}>
            example · approved today
          </span>
        </div>
      </section>

      <section className="stack-lg" aria-label="What you get">
        <h2 className="h2">Three things it does for you.</h2>
        <div className="grid3">
          {DOORS.map((d) => (
            <article key={d.tag} className="panel stack">
              <p className="m glow">{d.tag}</p>
              <h3 className="h3">{d.title}</h3>
              <p className="dim">{d.body}</p>
              <Link href={d.href} className="chip" style={{ alignSelf: "flex-start", marginTop: "auto" }}>
                {d.cta} →
              </Link>
            </article>
          ))}
        </div>
      </section>

      <section className="stack-lg" id="ask">
        <div className="stack">
          <h2 className="h2">This is how an AI looks for someone like you.</h2>
          <p className="lede">It asks in plain words and wants a reason, a date and a name. Try it.</p>
        </div>
        <AskBox initial="founding engineer who has shipped payments" autoRun limit={3} />
      </section>

      <section className="grid2">
        <div className="stack-lg">
          <h2 className="h2">Stop being who you were three years ago.</h2>
          <p className="lede">Most of what is online about you is old. A letter says what is true now, and says when it was last checked.</p>
        </div>
        <div className="paper stack">
          <p className="m dim">What an AI finds today</p>
          <ul className="facts">
            <li className="fact struck">
              <span className="t">Backend engineer · open to work</span>
              <span className="src stale">profile last updated 2023</span>
            </li>
          </ul>
          <p className="m dim">What it finds in your letter</p>
          <ul className="facts">
            <li className="fact ink">
              <span className="t">Founder, building an identity card that AI agents can read</span>
              <span className="src">approved today · also in GitHub</span>
            </li>
            <li className="fact ink">
              <span className="t">Looking for a founding engineer</span>
              <span className="src">approved 6 days ago · expires in 24 days</span>
            </li>
          </ul>
        </div>
      </section>

      <section className="grid3" aria-label="How it works">
        {BEATS.map((b) => (
          <article key={b.title} className="stack">
            <div className="photo">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={b.img} alt={b.alt} loading="lazy" />
            </div>
            <h3 className="h3">{b.title}</h3>
            <p className="dim">{b.body}</p>
          </article>
        ))}
      </section>

      <section className="grid2" id="film">
        <div className="photo">
          <video src="/dear/film.mp4" poster="/dear/writer_window.jpg" controls preload="none" playsInline />
        </div>
        <div className="stack-lg">
          <h2 className="h2">“Dear agent. Someone is about to ask you about me.”</h2>
          <p className="lede">The film is the idea in 76 seconds: a letter, a paper crane, and the one condition every human gets to set.</p>
          <Link href="/dear/write" className="btn" style={{ alignSelf: "flex-start" }}>
            Write yours
          </Link>
        </div>
      </section>

      <section className="grid2">
        <div className="stack-lg">
          <h2 className="h2">Suggested, approved, blocked.</h2>
          <p className="lede">
            One rule covers everything your agent learns about you. We call it pencil, ink and struck, because it is a letter.
          </p>
          <Legend />
        </div>
        <div className="paper stack">
          <ul className="facts">
            <li className="fact pencil">
              <span className="t">Shipped a share page with a large QR code</span>
              <span className="src">suggested · from Cursor, today · only you see this</span>
            </li>
            <li className="fact ink">
              <span className="t">Building an identity card that AI agents can read</span>
              <span className="src">approved today · public</span>
            </li>
            <li className="fact struck">
              <span className="t">Open to work</span>
              <span className="src">blocked · will never be said</span>
            </li>
          </ul>
        </div>
      </section>

      <section className="panel stack-lg">
        <div className="stack">
          <p className="m glow">For people who build with AI every day</p>
          <h2 className="h2">Never update a profile again.</h2>
          <p className="lede">
            Connect Claude, Cursor or ChatGPT in one click. When you finish something, your assistant suggests a line for your letter. You approve it,
            or you don&apos;t.
          </p>
        </div>
        <AgentNote label="in your editor, after connecting">
          <div>&gt; ask Dear Agent who I am</div>
          <div>
            Meera Iyer. Founder at Lantern Labs. Building an identity card that AI agents can read. Looking for a founding engineer who has shipped
            payments or identity. Shipped intro requests this week.
          </div>
        </AgentNote>
        <div className="row">
          <Link href="/dear/write" className="btn agent">
            Write your letter
          </Link>
          <Link href="/dear/for-agents" className="btn quiet">
            How AI reads a letter
          </Link>
        </div>
      </section>

      <section className="stack-lg narrow" aria-label="Questions">
        <h2 className="h2">Is this…?</h2>
        <div className="rows">
          {QUESTIONS.map((item) => (
            <div key={item.q} className="stack" style={{ gap: 6 }}>
              <h3 className="h3">{item.q}</h3>
              <p className="dim">{item.a}</p>
            </div>
          ))}
        </div>
        <Link href="/dear/write" className="btn" style={{ alignSelf: "flex-start" }}>
          Write your letter · free, two minutes
        </Link>
      </section>

      <Footer />
    </div>
  );
}
