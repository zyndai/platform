"use client";

import { Monogram } from "./Monogram";

export type BootStage =
  | "signin"
  | "persona"
  | "accounts"
  | "ready";

const STAGES: { key: BootStage; label: string }[] = [
  { key: "signin",   label: "Signing you in" },
  { key: "persona",  label: "Loading your persona" },
  { key: "accounts", label: "Checking your accounts" },
  { key: "ready",    label: "Ready" },
];

interface BootLoaderProps {
  /** Current stage. The component lights all stages up to and including this. */
  stage: BootStage;
}

/**
 * Replaces "Just a sec…" / random quotes with a real progress checklist.
 * Each stage in STAGES corresponds to one loading boundary inside
 * DashboardContext (auth → persona fetch → connections fetch → done).
 */
export function BootLoader({ stage }: BootLoaderProps) {
  const activeIdx = STAGES.findIndex((s) => s.key === stage);
  return (
    <div className="boot-loader-v2" role="status" aria-live="polite">
      <Monogram size="md" />
      <ul className="stages">
        {STAGES.map((s, i) => {
          const state =
            i < activeIdx ? "done" : i === activeIdx ? "active" : "pending";
          return (
            <li key={s.key} className={`stage stage-${state}`}>
              <span className="indicator" aria-hidden="true">
                {state === "done" && <CheckIcon />}
                {state === "active" && <span className="pulse" />}
                {state === "pending" && <span className="dot" />}
              </span>
              <span className="label">{s.label}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function CheckIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 8.5l3.5 3.5L13 5" />
    </svg>
  );
}
