import Link from "next/link";
import type { ReactNode } from "react";
import { ageLabel, expiresIn, isStale, SOURCE_LABEL } from "@/lib/dear/repo";
import type { Fact } from "@/lib/dear/types";

/** The agent: the letter, folded into a paper crane. */
export function Crane({ className, title }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 100 70" className={className} role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      <path d="M4 20 14 14 40 42 52 8 60 42 96 30 64 52 50 66 36 52Z" fill="currentColor" />
    </svg>
  );
}

/** The crane as a lit object, for hero moments. */
export function CraneLit({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 100 70" className={className} role="img" aria-label="A letter folded into a paper crane">
      <path d="M4 20 14 14 40 42 52 8 60 42 96 30 64 52 50 66 36 52Z" fill="#ece5d3" />
      <path d="M40 42 60 42 50 66Z" fill="#a59dff" opacity=".75" />
    </svg>
  );
}

const PUBLIC_NAV = [
  { href: "/dear/find", label: "Find someone" },
  { href: "/dear/for-agents", label: "For agents" },
  { href: "/dear/signin", label: "Sign in" },
];

const OWNER_NAV = [
  { href: "/dear/home", label: "Home" },
  { href: "/dear/inbox", label: "Inbox", count: true },
  { href: "/dear/sources", label: "Sources" },
  { href: "/dear/share", label: "Share" },
];

export function TopBar({ owner, current, inbox }: { owner?: boolean; current?: string; inbox?: number }) {
  const items = owner ? OWNER_NAV : PUBLIC_NAV;
  return (
    <header className="top">
      <Link href="/dear" className="brand">
        <Crane />
        Dear Agent
      </Link>
      <nav className="nav" aria-label={owner ? "Your letter" : "Site"}>
        {items.map((item) => (
          <Link key={item.href} href={item.href} aria-current={current === item.href ? "page" : undefined}>
            {item.label}
            {"count" in item && inbox ? <span className="count">{inbox}</span> : null}
          </Link>
        ))}
        {owner ? (
          <Link href="/dear/l/meera-iyer">My letter</Link>
        ) : (
          <Link href="/dear/write" className="btn small agent" style={{ color: "#14121f" }}>
            Write your letter
          </Link>
        )}
      </nav>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="foot">
      <span className="zynd m">
        powered by
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/dear/zynd-mark.png" alt="" />
        <span style={{ fontFamily: "var(--serif)", fontSize: 22, textTransform: "none", letterSpacing: 0, color: "var(--chalk)" }}>Zynd</span>
      </span>
      <nav className="nav" aria-label="Footer">
        <Link href="/dear/write">Write your letter</Link>
        <Link href="/dear/find">Find someone</Link>
        <Link href="/dear/for-agents">For agents</Link>
      </nav>
      <span className="banner">UI branch · example data · not connected to the backend</span>
    </footer>
  );
}

/** A note in the agent's voice. */
export function AgentNote({ children, label = "your agent" }: { children: ReactNode; label?: string }) {
  return (
    <div className="note">
      <div className="who">
        <Crane />
        {label}
      </div>
      {children}
    </div>
  );
}

/** Source, date and approval for one line: the receipt the review asked for on every public fact. */
export function Receipt({ fact }: { fact: Fact }) {
  const left = expiresIn(fact);
  const also = fact.alsoIn?.length ? ` · also in ${fact.alsoIn.map((s) => SOURCE_LABEL[s]).join(", ")}` : "";
  if (fact.state === "struck") return <span className="src">struck · will never be said</span>;
  if (fact.state === "pencil") {
    return (
      <span className={`src${isStale(fact.asOf) ? " stale" : ""}`}>
        {SOURCE_LABEL[fact.source]} · last true {ageLabel(fact.asOf)}
        {isStale(fact.asOf) ? " · still true?" : ""}
      </span>
    );
  }
  return (
    <span className="src">
      {SOURCE_LABEL[fact.source]} · approved {ageLabel(fact.approvedAt ?? fact.asOf)}
      {also}
      {left !== null ? (left >= 0 ? ` · expires in ${left} days` : " · expired") : ""}
    </span>
  );
}

export function FactLine({ fact, children }: { fact: Fact; children?: ReactNode }) {
  return (
    <li className={`fact ${fact.state}`}>
      <span className="t">{fact.text}</span>
      <Receipt fact={fact} />
      {children ? <span className="acts">{children}</span> : null}
    </li>
  );
}

export function Legend() {
  return (
    <div className="legend">
      <span className="p">
        <b>pencil</b> = suggested · only you see it
      </span>
      <span className="i">
        <b>ink</b> = approved by you · public
      </span>
      <span className="s">
        <b>struck</b> = blocked · never said
      </span>
    </div>
  );
}
