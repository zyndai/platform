"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui";
import { useDashboard } from "@/contexts/DashboardContext";
import { patchOnboardingMeta, readOnboardingMeta } from "@/lib/onboarding";
import { getDashboardTourSteps, getSearchShortcut, START_TOUR_EVENT, type TourPlacement } from "@/lib/tour";

/** Below this viewport width the sidebar is a slide-in drawer, not a
 *  persistent rail — the tour only makes sense on wider screens. */
const MIN_TOUR_WIDTH = 900;
/** Let the dashboard shell settle before auto-starting. */
const AUTO_START_DELAY_MS = 900;
const CARD_WIDTH = 280;
const SPOTLIGHT_PAD = 6;
const CARD_GAP = 16;
const VIEWPORT_MARGIN = 12;

interface Rect {
  top: number;
  left: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

function measureTarget(target: string): Rect | null {
  const el = document.querySelector(`[data-tour="${target}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { top: r.top, left: r.left, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
}

function cardPosition(rect: Rect, placement: TourPlacement, cardHeight: number) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  let top: number;
  let left: number;

  if (placement === "right") {
    top = rect.top + rect.height / 2 - cardHeight / 2;
    left = rect.right + CARD_GAP;
  } else if (placement === "top") {
    top = rect.top - cardHeight - CARD_GAP;
    left = rect.left + rect.width / 2 - CARD_WIDTH / 2;
  } else {
    top = rect.bottom + CARD_GAP;
    left = rect.left + rect.width / 2 - CARD_WIDTH / 2;
  }

  top = Math.min(Math.max(top, VIEWPORT_MARGIN), vh - cardHeight - VIEWPORT_MARGIN);
  left = Math.min(Math.max(left, VIEWPORT_MARGIN), vw - CARD_WIDTH - VIEWPORT_MARGIN);
  return { top, left };
}

interface GuidedTourProps {
  sidebarCollapsed: boolean;
  onExpandSidebar: () => void;
}

export default function GuidedTour({ sidebarCollapsed, onExpandSidebar }: GuidedTourProps) {
  const { user, onboardingStep, knownOnboarded } = useDashboard();
  const [active, setActive] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const [cardHeight, setCardHeight] = useState(120);
  const cardRef = useRef<HTMLDivElement>(null);
  const autoTried = useRef(false);

  const tourSteps = useMemo(() => getDashboardTourSteps(getSearchShortcut()), []);

  const step = active ? tourSteps[stepIndex] : null;
  const isLast = stepIndex === tourSteps.length - 1;

  const finish = useCallback((markSeen: boolean) => {
    setActive(false);
    if (markSeen) void patchOnboardingMeta({ dashboard_tour_seen: true });
  }, []);

  const next = useCallback(() => {
    setStepIndex((i) => {
      if (i >= tourSteps.length - 1) {
        finish(true);
        return i;
      }
      return i + 1;
    });
  }, [finish]);

  const back = useCallback(() => setStepIndex((i) => Math.max(0, i - 1)), []);

  // Auto-start once, for first-time visitors who've finished onboarding and
  // haven't seen the tour yet. Manual replays (below) bypass this gate.
  useEffect(() => {
    if (autoTried.current || active) return;
    if (!user) return;
    if (window.innerWidth < MIN_TOUR_WIDTH) return;
    const meta = readOnboardingMeta(user);
    const eligible = (onboardingStep === "done" || knownOnboarded) && !meta.dashboard_tour_seen;
    if (!eligible) return;

    autoTried.current = true;
    const t = window.setTimeout(() => {
      setRect(null);
      setStepIndex(0);
      setActive(true);
    }, AUTO_START_DELAY_MS);
    return () => window.clearTimeout(t);
  }, [user, onboardingStep, knownOnboarded, active]);

  useEffect(() => {
    const handler = () => {
      if (window.innerWidth < MIN_TOUR_WIDTH) return;
      // Clear any rect measured by a previous run before jumping back to
      // step 0 -- otherwise the first card briefly renders at the last
      // run's position until the target is re-measured.
      setRect(null);
      setStepIndex(0);
      setActive(true);
    };
    window.addEventListener(START_TOUR_EVENT, handler);
    return () => window.removeEventListener(START_TOUR_EVENT, handler);
  }, []);

  // A collapsed sidebar hides nav labels — expand it so the tour reads clearly.
  useEffect(() => {
    if (active && sidebarCollapsed) onExpandSidebar();
  }, [active, sidebarCollapsed, onExpandSidebar]);

  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); finish(true); }
      else if (e.key === "ArrowRight" || e.key === "Enter") { e.preventDefault(); next(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); back(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, finish, next, back]);

  useEffect(() => {
    if (!active || !step) return;
    const measure = () => {
      setRect(measureTarget(step.target));
      setViewport({ width: window.innerWidth, height: window.innerHeight });
    };
    measure();
    // Re-measure a tick later too — covers the sidebar expanding from collapsed.
    const raf = requestAnimationFrame(measure);
    window.addEventListener("resize", measure);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", measure);
    };
  }, [active, step, sidebarCollapsed]);

  useLayoutEffect(() => {
    if (cardRef.current) setCardHeight(cardRef.current.getBoundingClientRect().height);
  }, [step, rect]);

  if (!active || !step || !rect || viewport.width === 0) return null;

  const hole = {
    top: rect.top - SPOTLIGHT_PAD,
    left: rect.left - SPOTLIGHT_PAD,
    right: rect.right + SPOTLIGHT_PAD,
    bottom: rect.bottom + SPOTLIGHT_PAD,
  };
  const pos = cardPosition(rect, step.placement, cardHeight);

  return (
    <div className="tour-root" role="dialog" aria-modal="true" aria-label="Guided tour">
      <div
        className="tour-mask"
        style={{ top: 0, left: 0, width: viewport.width, height: Math.max(hole.top, 0) }}
      />
      <div
        className="tour-mask"
        style={{ top: hole.bottom, left: 0, width: viewport.width, height: Math.max(viewport.height - hole.bottom, 0) }}
      />
      <div
        className="tour-mask"
        style={{ top: hole.top, left: 0, width: Math.max(hole.left, 0), height: hole.bottom - hole.top }}
      />
      <div
        className="tour-mask"
        style={{ top: hole.top, left: hole.right, width: Math.max(viewport.width - hole.right, 0), height: hole.bottom - hole.top }}
      />
      <div
        className="tour-ring"
        style={{ top: hole.top, left: hole.left, width: hole.right - hole.left, height: hole.bottom - hole.top }}
      />

      <div
        key={stepIndex}
        ref={cardRef}
        className="tour-card"
        data-placement={step.placement}
        style={{ top: pos.top, left: pos.left, width: CARD_WIDTH }}
      >
        <button type="button" className="tour-close" onClick={() => finish(true)} aria-label="Skip tour">
          <X size={14} strokeWidth={1.5} />
        </button>
        <div className="tour-card-title">{step.title}</div>
        <div className="tour-card-body">{step.body}</div>
        <div className="tour-card-footer">
          <div className="tour-footer-left">
            {!isLast && (
              <button type="button" className="tour-skip-link" onClick={() => finish(true)}>
                Skip
              </button>
            )}
            <div className="tour-dots" aria-hidden="true">
              {tourSteps.map((s, i) => (
                <span key={s.target} className={`tour-dot ${i === stepIndex ? "active" : ""}`} />
              ))}
            </div>
          </div>
          <div className="tour-card-actions">
            {stepIndex > 0 && (
              <Button variant="tertiary" size="sm" onClick={back}>Back</Button>
            )}
            <Button variant="primary" size="sm" onClick={next}>{isLast ? "Done" : "Next"}</Button>
          </div>
        </div>
      </div>
    </div>
  );
}
