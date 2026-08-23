/**
 * Step script for the in-dashboard guided tour. Each step targets a
 * persistent chrome element via its `data-tour` attribute, so the tour
 * survives client-side route changes (the sidebar/topbar never unmount).
 */

export type TourPlacement = "right" | "top" | "bottom";

export interface TourStep {
  /** Matches the `data-tour` attribute on the target element. */
  target: string;
  title: string;
  body: string;
  placement: TourPlacement;
}

/** Returns the platform-appropriate search shortcut label. */
export function getSearchShortcut(): string {
  if (typeof navigator === "undefined") return "⌘K";
  // navigator.platform is deprecated but has universal support and zero overhead.
  // Apple reports "MacIntel", "MacPPC", "iPhone", "iPad" — all start with "Mac" or "iP".
  const p = navigator.platform.toLowerCase();
  return p.startsWith("mac") || p.startsWith("ip") ? "⌘K" : "Ctrl+K";
}

export function getDashboardTourSteps(shortcutKey: string): TourStep[] {
  return [
  {
    target: "tour-search",
    title: "Jump to anything",
    body: `Press ${shortcutKey} to search people, threads, and meetings without leaving the keyboard.`,
    placement: "right",
  },
  {
    target: "tour-nav-chat",
    title: "This is home",
    body: "Your persona's live feed — everything it notices or does shows up here first.",
    placement: "right",
  },
  {
    target: "tour-nav-inbox",
    title: "Approvals live here",
    body: "Intros, replies, and decisions that need your OK land in the inbox.",
    placement: "right",
  },
  {
    target: "tour-nav-messages",
    title: "Every thread",
    body: "Full conversation history between your persona and the people it talks to.",
    placement: "right",
  },
  {
    target: "tour-nav-meetings",
    title: "Meetings, handled",
    body: "Scheduling requests and calendar holds your persona is managing for you.",
    placement: "right",
  },
  {
    target: "tour-nav-people",
    title: "Your network",
    body: "Everyone your persona has met or is getting to know on your behalf.",
    placement: "right",
  },
  {
    target: "tour-nav-groups",
    title: "Shared spaces",
    body: "Groups where your persona coordinates with other people's personas.",
    placement: "right",
  },
  {
    target: "tour-you-settings",
    title: "Tune your persona",
    body: "Your brief, connections, pages, and settings all live down here — come back anytime.",
    placement: "top",
  },
  {
    target: "tour-user-card",
    title: "That's you",
    body: "Your profile, public agent card, and sign-out — you're all set.",
    placement: "top",
  },
  ];
}

/** Dispatched by any "replay tour" affordance; GuidedTour listens for this. */
export const START_TOUR_EVENT = "zynd:start-tour";

export function startGuidedTour() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(START_TOUR_EVENT));
  }
}
