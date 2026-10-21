"use client";

import { Check } from "lucide-react";
import { EDITION_FONT_VARS } from "./fonts";
import { MumbaiSkyline } from "./mumbai-skyline";
import { EDITION_NAME, HERE_FOR, HERE_FOR_LABEL, isEditionPickable, type CardEdition } from "@/lib/editions";
import "./edition.css";

interface Person {
  name: string;
  headline: string;
  avatarSrc: string | null;
}

interface Props {
  value: CardEdition | null;
  onChange: (next: CardEdition | null) => void;
  person: Person;
}

function initialsOf(name: string): string {
  return (name || "?").split(/\s+/).map((p) => p[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
}

function MiniPerson({ person }: { person: Person }) {
  return (
    <span className="ed-mini-person">
      {person.avatarSrc ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={person.avatarSrc} alt="" />
      ) : <span className="ed-mini-ph" aria-hidden>{initialsOf(person.name)}</span>}
      <span style={{ minWidth: 0 }}>
        <span className="ed-mini-name" style={{ display: "block" }}>{person.name || "Your name"}</span>
        {person.headline && <span className="ed-mini-head" style={{ display: "block" }}>{person.headline}</span>}
      </span>
    </span>
  );
}

/** Classic or the limited-edition look, plus the edition's optional "here for". */
export function EditionPicker({ value, onChange, person }: Props) {
  // A card already on the edition keeps it after picking closes; it just can't be newly chosen.
  const canPickMumbai = value?.id === "mumbai-26" || isEditionPickable("mumbai-26");
  const mumbai = value?.id === "mumbai-26" ? value : null;

  return (
    <div className={`ed ed-pick ${EDITION_FONT_VARS}`}>
      <div className="ed-pick-tiles" role="group" aria-label="Card style">
        <button type="button" className="ed-tile" aria-pressed={!value} onClick={() => onChange(null)}>
          <span className="ed-mini ed-mini-classic" aria-hidden><MiniPerson person={person} /></span>
          <span className="ed-tile-title">Classic</span>
          <span className="ed-tile-sub">The standard Zynd card.</span>
          {!value && <span className="ed-tile-check" aria-hidden><Check size={14} /></span>}
        </button>
        <button type="button" className="ed-tile" aria-pressed={!!mumbai} disabled={!canPickMumbai}
          onClick={() => onChange(mumbai ?? { id: "mumbai-26", mood: "night", here_for: null })}>
          <span className="ed-mini ed-mini-edition" aria-hidden>
            <MumbaiSkyline idPrefix="ed-pick-tile" focus="bottom" simple />
            <MiniPerson person={person} />
          </span>
          <span className="ed-tile-tag">{canPickMumbai ? "Limited edition · Nov 2026" : "Edition closed"}</span>
          <span className="ed-tile-title">{EDITION_NAME["mumbai-26"]}</span>
          <span className="ed-tile-sub">Mumbai skyline artwork, a “Here for” tag and a full-screen QR for meeting people in person.</span>
          {mumbai && <span className="ed-tile-check" aria-hidden><Check size={14} /></span>}
        </button>
      </div>

      {mumbai && (
        <>
          <div>
            <div className="ed-pick-label">Here for</div>
            <div className="ed-here" role="group" aria-label="Here for">
              {HERE_FOR.map((option) => (
                <button key={option} type="button" className="ed-here-opt" aria-pressed={mumbai.here_for === option}
                  onClick={() => onChange({ ...mumbai, here_for: mumbai.here_for === option ? null : option })}>
                  {HERE_FOR_LABEL[option]}
                </button>
              ))}
            </div>
          </div>
          <div className="ed-pick-note">Shown on your card to everyone who opens it. Switch back to Classic any time.</div>
        </>
      )}
    </div>
  );
}
