import { CARDS_API } from "@/lib/cards";

const ENABLED = process.env.NEXT_PUBLIC_S04_EVENTS === "true";

/** Fire-and-forget client event. Never throws. */
export function track(event: string, meta?: Record<string, unknown>, handle?: string): void {
  if (!ENABLED || typeof window === "undefined") return;
  const body = JSON.stringify({
    events: [{ event, handle, meta }],
  });
  try {
    const url = `${CARDS_API}/events`;
    if (typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function") {
      const blob = new Blob([body], { type: "application/json" });
      if (navigator.sendBeacon(url, blob)) return;
    }
    void fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    // ignore
  }
}

/** Server-side agent_fetch logger for route handlers. Non-blocking. */
export function logAgentFetch(
  endpoint: string,
  userAgent: string | null | undefined,
  handle?: string,
): void {
  if (process.env.NEXT_PUBLIC_S04_EVENTS !== "true") return;
  const body = JSON.stringify({
    events: [{ event: "agent_fetch", handle, meta: { endpoint } }],
  });
  try {
    void fetch(`${CARDS_API}/events`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(userAgent ? { "User-Agent": userAgent } : {}),
      },
      body,
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    // ignore
  }
}
