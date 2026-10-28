"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { CARDS_API } from "@/lib/cards";
import {
  MAX_LINK_CHARS,
  MAX_NAME_CHARS,
  STATUS_TEXT,
  displayUrl,
  parseVisibilityReport,
  validateVisibilityInput,
  visibilityCta,
  visibilityStatus,
  type VisibilityReport,
} from "@/lib/visibility";

// The API gives the model 30s; this leaves room for the card lookup and the network.
const REQUEST_TIMEOUT_MS = 45_000;

type Check =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "done"; report: VisibilityReport; link: string | null };

async function readError(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: unknown };
    if (typeof data.detail === "string" && data.detail.trim()) return data.detail;
  } catch (error) {
    console.warn("visibility: error response was not JSON", error);
  }
  return `Something went wrong (${res.status}). Try again in a minute.`;
}

async function requestReport(name: string, link: string | null): Promise<VisibilityReport> {
  let res: Response;
  try {
    res = await fetch(`${CARDS_API}/cards/visibility/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(link ? { name, link } : { name }),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new Error("The AI took too long to answer. Try again in a minute.", { cause: error });
    }
    throw new Error("Couldn't reach Zynd. Check your connection and try again.", { cause: error });
  }
  if (!res.ok) throw new Error(await readError(res));
  const report = parseVisibilityReport(await res.json());
  if (!report) throw new Error("The answer came back in a shape we didn't expect. Try again.");
  return report;
}

export function VisibilityChecker() {
  const [name, setName] = useState("");
  const [link, setLink] = useState("");
  const [check, setCheck] = useState<Check>({ phase: "idle" });
  const isLoading = check.phase === "loading";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isLoading) return;
    const invalid = validateVisibilityInput(name, link);
    if (invalid) {
      setCheck({ phase: "error", message: invalid });
      return;
    }
    const cleanLink = link.trim() || null;
    setCheck({ phase: "loading" });
    try {
      const report = await requestReport(name.trim(), cleanLink);
      setCheck({ phase: "done", report, link: cleanLink });
    } catch (error) {
      setCheck({ phase: "error", message: error instanceof Error ? error.message : "Something went wrong. Try again." });
    }
  }

  return (
    <div className="vz">
      <section className="dc-hero vz-hero">
        <div className="dc-hero-copy">
          <span className="dc-eyebrow"><span className="dc-eyebrow-dot" aria-hidden="true" />AI visibility check</span>
          {/* div, not h1: globals.css sets h1 { font-size: 6rem } */}
          <div className="dc-title" role="heading" aria-level={1}>What does AI say about you?</div>
          <p className="dc-lede">
            Your next collaborator won&apos;t Google you. Their agent will. See what an AI with web
            search says about you today, before anyone asks it.
          </p>
        </div>
        <form className="vz-form" onSubmit={handleSubmit} noValidate aria-busy={isLoading}>
          <label className="vz-field">
            <span className="dc-label">Your name</span>
            <input
              className="vz-input"
              name="name"
              autoComplete="name"
              required
              maxLength={MAX_NAME_CHARS}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Ada Lovelace"
              disabled={isLoading}
            />
          </label>
          <label className="vz-field">
            <span className="dc-label">A link about you <span className="vz-optional">(optional)</span></span>
            <input
              className="vz-input"
              name="link"
              type="url"
              inputMode="url"
              maxLength={MAX_LINK_CHARS}
              value={link}
              onChange={(e) => setLink(e.target.value)}
              placeholder="https://linkedin.com/in/you"
              disabled={isLoading}
            />
          </label>
          <button type="submit" className="dc-btn dc-btn-primary vz-submit" disabled={isLoading}>
            {isLoading ? "Asking the AI…" : "See what AI says"}
          </button>
        </form>
      </section>

      <div aria-live="polite">
        {isLoading && (
          <div className="vz-panel vz-loading">
            <span className="vz-spinner" aria-hidden="true" />
            <div>
              <div className="vz-panel-title">Searching the web like an AI would…</div>
              <p className="vz-muted">This usually takes 10 to 20 seconds.</p>
            </div>
          </div>
        )}
        {check.phase === "error" && (
          <div className="vz-panel vz-error" role="alert">{check.message}</div>
        )}
        {check.phase === "done" && <VisibilityResult report={check.report} link={check.link} />}
      </div>
    </div>
  );
}

function VisibilityResult({ report, link }: { report: VisibilityReport; link: string | null }) {
  const status = visibilityStatus(report);
  const cta = visibilityCta(report, link);

  return (
    <section className="vz-panel vz-result" aria-label="Your AI visibility report">
      <div className={`vz-status is-${status}`}>{STATUS_TEXT[status]}</div>

      <div className="vz-panel-title">What AI says about you today</div>
      {report.found ? (
        <p className="vz-answer">{report.answer}</p>
      ) : (
        <p className="vz-answer vz-muted">
          It searched the web and couldn&apos;t find anything it was sure was about you. To an agent
          looking for you, that means you don&apos;t exist yet.
        </p>
      )}

      {report.cited_urls.length > 0 && (
        <div className="vz-sources">
          <div className="dc-label">Sources it used</div>
          <ol>
            {report.cited_urls.map((url) => (
              <li key={url}>
                <a href={url} target="_blank" rel="noopener noreferrer nofollow">{displayUrl(url)}</a>
              </li>
            ))}
          </ol>
        </div>
      )}

      <p className="vz-note">
        Answer from {report.model_label} via API. The ChatGPT app may answer differently.
      </p>

      <div className="vz-cta">
        <p className="vz-cta-text">
          {report.zynd_card
            ? report.zynd_card.claimed
              ? "You have a Zynd card that agents can read."
              : "There's a Zynd card with your name that nobody has claimed yet."
            : "A Zynd card gives agents one accurate, citable page about you."}
        </p>
        <Link href={cta.href} className="dc-btn dc-btn-primary">{cta.label}</Link>
      </div>
    </section>
  );
}
