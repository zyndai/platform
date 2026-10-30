"use client";

import { useRef, useState } from "react";
import { Check, Copy, Eye } from "lucide-react";
import { cardsSiteOrigin } from "@/lib/cards";
import { LENSES, lensPath, type LensId, type LensSectionId } from "@/lib/lenses";
import "./share-for.css";

const SECTION_NAMES: Record<LensSectionId, string> = {
  exploring: "what you're exploring",
  helped: "who you've helped",
  experience: "experience",
  social: "LinkedIn and X",
  github: "GitHub",
  writing: "writing",
  gallery: "your work",
  projects: "projects",
  beacon: "your live ask",
  explore: "similar profiles",
};

type CopyState = "idle" | "copied" | "failed";

/** "Share for…": the owner picks who they are sending the card to and copies that
 *  lens link (lib/lenses.ts). The link is the same public card, rearranged. */
export function ShareFor({ handle }: { handle: string }) {
  const [picked, setPicked] = useState<LensId>(LENSES[0].id);
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const urlField = useRef<HTMLInputElement>(null);
  const lens = LENSES.find((l) => l.id === picked) ?? LENSES[0];
  const path = lensPath(handle, lens.id);
  const url = `${cardsSiteOrigin()}${path}`;
  const leads = lens.lead.slice(0, 3).map((id) => SECTION_NAMES[id]).join(", ");

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopyState("copied");
    } catch {
      // Clipboard access is denied outside a secure context or by browser policy.
      urlField.current?.select();
      setCopyState("failed");
    }
  }

  return (
    <section className="oh-panel oh-wide sf" aria-labelledby="sf-heading">
      <p className="oh-eyebrow">ONE CARD, THE RIGHT ANGLE</p>
      <h2 id="sf-heading" className="oh-heading-icon"><Eye size={20} aria-hidden="true" />Share for a specific reader</h2>
      <p>
        Send a link that opens your card with what that reader cares about first. It is the same
        public card, rearranged, so search engines and AI agents still see one page.
      </p>
      <fieldset className="sf-options">
        <legend>Who are you sending it to?</legend>
        {LENSES.map((l) => (
          <label key={l.id} className={`sf-option${l.id === picked ? " is-picked" : ""}`}>
            <input
              type="radio"
              name="share-for"
              value={l.id}
              checked={l.id === picked}
              onChange={() => { setPicked(l.id); setCopyState("idle"); }}
            />
            <span className="sf-option-name">{l.audience.charAt(0).toUpperCase() + l.audience.slice(1)}</span>
          </label>
        ))}
      </fieldset>
      <p className="sf-leads">Opens with {leads}.</p>
      <div className="sf-link-row">
        <label className="sf-sr" htmlFor="sf-url">Link for {lens.audience}</label>
        <input id="sf-url" ref={urlField} className="sf-url" readOnly value={url} onFocus={(e) => e.currentTarget.select()} />
        <button type="button" className="oh-button" onClick={copy}>
          {copyState === "copied" ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
          Copy link
        </button>
        <a className="oh-button oh-outline" href={path} target="_blank" rel="noreferrer">Preview</a>
      </div>
      <p className="sf-status" role="status" aria-live="polite">
        {copyState === "copied" && `Copied the link for ${lens.audience}.`}
        {copyState === "failed" && "Couldn't copy automatically. The link is selected: press Ctrl+C or ⌘C."}
      </p>
    </section>
  );
}
