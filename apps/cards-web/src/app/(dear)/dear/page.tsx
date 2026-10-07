import Link from "next/link";
import { AskBox } from "@/components/dear/ask-box";
import { AgentNote, Footer, Legend, TopBar } from "@/components/dear/ui";

const BEATS = [
  {
    img: "/dear/desk.jpg",
    alt: "A blank sheet of paper on a desk under a lamp at night",
    title: "Say what is true today",
    body: "What you are building, what you are looking for, who you can help. Your agent pencils in what it finds on LinkedIn, GitHub and X. Nothing is public until you ink it.",
  },
  {
    img: "/dear/crane_desk.jpg",
    alt: "The letter folded into a paper crane, glowing on the desk",
    title: "Decide what it may do",
    body: "It can speak for you, find the right people and put other agents to work. Before it promises anything in your name, it asks you first.",
  },
  {
    img: "/dear/two_cranes.jpg",
    alt: "Two paper cranes meeting on a wire at dawn",
    title: "Let it say hello",
    body: "When someone's agent is looking for a person like you, yours answers. If it is a fit, you get one request to approve, not a cold message.",
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
            Dear Agent is the letter you write once, so every AI that is asked about you has the truth, and your permission.
          </p>
          <div className="row">
            <Link href="/dear/write" className="btn">
              Write your letter
            </Link>
            <a href="#film" className="btn quiet">
              Watch the film · 1:16
            </a>
          </div>
          <p className="m dim">Free · about two minutes · nothing goes public until you sign</p>
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

      <section className="stack-lg">
        <div className="stack">
          <h2 className="h2">Ask the way an agent would.</h2>
          <p className="lede">This is what happens when someone&apos;s AI goes looking for a person. Try it.</p>
        </div>
        <AskBox initial="founding engineer who has shipped payments" autoRun limit={3} />
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
          <h2 className="h2">Pencil, ink, struck.</h2>
          <p className="lede">
            One rule covers everything your agent learns about you, from your LinkedIn to what you shipped this morning.
          </p>
          <Legend />
        </div>
        <div className="paper stack">
          <ul className="facts">
            <li className="fact pencil">
              <span className="t">Shipped a share page with a large QR code</span>
              <span className="src">Cursor · last true today</span>
            </li>
            <li className="fact ink">
              <span className="t">Building an identity card that AI agents can read</span>
              <span className="src">Written by you · approved today · also in GitHub</span>
            </li>
            <li className="fact struck">
              <span className="t">Open to work</span>
              <span className="src">struck · will never be said</span>
            </li>
          </ul>
        </div>
      </section>

      <section className="panel stack-lg">
        <div className="stack">
          <p className="m glow">For people who build with AI every day</p>
          <h2 className="h2">Your letter keeps itself current.</h2>
          <p className="lede">
            Connect Claude, Cursor or ChatGPT in one click. When you finish something, your assistant pencils it into your letter. You ink it, or you
            don&apos;t.
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
            How agents read a letter
          </Link>
        </div>
      </section>

      <Footer />
    </div>
  );
}
