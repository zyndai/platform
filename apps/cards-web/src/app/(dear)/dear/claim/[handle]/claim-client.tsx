"use client";

import Link from "next/link";
import { useState } from "react";
import { AgentNote, CraneLit, Legend } from "@/components/dear/ui";
import { ageLabel, SOURCE_LABEL } from "@/lib/dear/repo";
import type { Letter } from "@/lib/dear/types";

type Step = "start" | "other" | "sent" | "mismatch" | "claimed" | "remove" | "removed";

/**
 * Claiming a page that was built from public data (slice S03).
 *
 * Claiming is not a separate account system: it is signing in with the
 * account the page was built from. LinkedIn sign-in whose profile matches the
 * page's LinkedIn URL claims it at once. Anything else (GitHub, Google, no
 * LinkedIn) cannot prove the match by itself, so it goes to a short check
 * instead of being refused. "This is not me" and "remove it" need no account.
 *
 * After a claim, every line on the page is in pencil: nothing the scrape
 * found is public until the person inks it.
 */
export function ClaimClient({ letter }: { letter: Letter }) {
  const [step, setStep] = useState<Step>("start");
  const [email, setEmail] = useState("");
  const first = letter.name.split(" ")[0];

  if (step === "claimed") {
    return (
      <div className="paper stack-lg rise">
        <CraneLit className="crane-hero" />
        <h1 className="h2">It&apos;s yours, {first}.</h1>
        <p className="dim" style={{ fontSize: 23 }}>
          The page that was built about you is now a draft only you can see. Here is what was found. None of it is public until you ink it.
        </p>
        <Legend />
        <ul className="facts">
          {letter.facts.map((f) => (
            <li key={f.id} className="fact pencil">
              <span className="t">{f.text}</span>
              <span className="src">
                {SOURCE_LABEL[f.source]} · last true {ageLabel(f.asOf)}
              </span>
            </li>
          ))}
        </ul>
        <div className="row">
          <Link href="/dear/write" className="btn">
            Write my letter
          </Link>
          <span className="m dim">You will ink, rewrite or strike each line</span>
        </div>
      </div>
    );
  }

  if (step === "removed") {
    return (
      <div className="paper stack rise">
        <h1 className="h2">Removed.</h1>
        <p className="dim" style={{ fontSize: 23 }}>
          This page is hidden now and will be deleted after a short check that the request is genuine. We will not build another one about you.
        </p>
        <Link href="/dear" className="btn quiet" style={{ alignSelf: "flex-start" }}>
          Back to Dear Agent
        </Link>
      </div>
    );
  }

  return (
    <div className="stack-lg">
      <header className="stack">
        <span className="stamp warn" style={{ alignSelf: "flex-start" }}>
          built from public data · not written by {first}
        </span>
        <h1 className="display" style={{ fontSize: "clamp(40px, 6vw, 60px)" }}>
          Is this you, {first}?
        </h1>
        <p className="lede">
          Someone&apos;s agent went looking for a person like you, so a page was started from what is public. You did not write it. It is hidden from AI and
          search until you do.
        </p>
      </header>

      <div className="paper stack">
        <p className="m dim">What was found</p>
        <p style={{ fontSize: 30 }}>{letter.name}</p>
        <p className="dim" style={{ fontSize: 21 }}>
          {letter.headline} · {letter.location}
        </p>
        <ul className="facts">
          {letter.facts.map((f) => (
            <li key={f.id} className="fact pencil">
              <span className="t">{f.text}</span>
              <span className="src">
                {SOURCE_LABEL[f.source]} · last true {ageLabel(f.asOf)}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {(step === "start" || step === "mismatch") && (
        <div className="paper stack">
          <h2 className="h3">Yes, this is me</h2>
          <p className="dim">Sign in with the LinkedIn account this page was built from. That is the proof; there is nothing else to fill in.</p>
          {step === "mismatch" && (
            <AgentNote>
              <div>
                That LinkedIn account is not the one this page was built from, so I can&apos;t hand it over on that alone. Try the other account, or use the check
                below.
              </div>
            </AgentNote>
          )}
          <div className="row">
            <button className="btn" onClick={() => setStep("claimed")}>
              Continue with LinkedIn
            </button>
            <button className="btn quiet" onClick={() => setStep("other")}>
              I don&apos;t use LinkedIn
            </button>
          </div>
          <button className="tap" style={{ alignSelf: "flex-start" }} onClick={() => setStep("mismatch")}>
            Preview: what a non-matching account sees
          </button>
        </div>
      )}

      {step === "other" && (
        <div className="paper stack rise">
          <h2 className="h3">Another way to show it&apos;s you</h2>
          <p className="dim">
            Sign in with GitHub or Google, then give us a work email or a link you control that this page already mentions. A person checks it, usually
            within a day. The page stays hidden meanwhile.
          </p>
          <label className="field">
            <span className="k">Work email, or a link to a profile you control</span>
            <input id="claim-proof" className="fill wide" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com or github.com/you" autoComplete="off" />
          </label>
          <div className="row">
            <button className="btn" disabled={!email.trim()} onClick={() => setStep("sent")}>
              Send for a check
            </button>
            <button className="btn quiet" onClick={() => setStep("start")}>
              Back
            </button>
          </div>
        </div>
      )}

      {step === "sent" && (
        <div className="paper stack rise">
          <h2 className="h3">Sent for a check.</h2>
          <AgentNote>
            <div>I will email you when a person has looked, usually within a day. Until then this page stays hidden and nobody else can claim it.</div>
          </AgentNote>
          <span className="stamp agent" style={{ alignSelf: "flex-start" }}>
            claim pending
          </span>
        </div>
      )}

      {step !== "remove" ? (
        <div className="panel stack">
          <h2 className="h3">No, or I don&apos;t want this</h2>
          <p className="dim">You do not need an account to have it taken down.</p>
          <div className="row">
            <button className="btn small quiet" onClick={() => setStep("remove")}>
              This is me: remove it
            </button>
            <button className="btn small quiet" onClick={() => setStep("removed")}>
              This is not me
            </button>
          </div>
        </div>
      ) : (
        <div className="panel stack rise">
          <h2 className="h3">Remove this page?</h2>
          <p className="dim">It will be hidden at once. We will not rebuild it from public data.</p>
          <div className="row">
            <button className="btn small agent" onClick={() => setStep("removed")}>
              Yes, remove it
            </button>
            <button className="btn small quiet" onClick={() => setStep("start")}>
              Keep it for now
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
