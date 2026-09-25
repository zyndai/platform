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
    <div className="boot-loader-v2" role="status" aria-live="polite" aria-label={STAGES[activeIdx]?.label || "Loading"}>
      <div className="boot-app-frame">
        <aside className="boot-sidebar-skel">
          <div className="boot-brand-skel">
            <Monogram size="sm" />
            <span className="boot-skel-line boot-skel-brand" />
          </div>
          <span className="boot-skel-input" />
          <div className="boot-nav-skel">
            {Array.from({ length: 6 }).map((_, i) => (
              <span key={i} className="boot-skel-nav-row">
                <span />
                <i />
              </span>
            ))}
          </div>
        </aside>
        <main className="boot-main-skel">
          <div className="boot-top-skel">
            <span className="boot-skel-line boot-skel-title" />
            <span className="boot-skel-pill" />
          </div>
          <div className="boot-card-skel boot-card-wide" />
          <div className="boot-grid-skel">
            {Array.from({ length: 4 }).map((_, i) => (
              <span key={i} className="boot-card-skel" />
            ))}
          </div>
        </main>
      </div>
      <span className="sr-only">{STAGES[activeIdx]?.label || "Loading"}</span>
    </div>
  );
}
