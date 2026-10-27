import { CARDS_API } from "@/lib/cards";

export const eventsEnabled = (process.env.NEXT_PUBLIC_S04_EVENTS ?? "true") === "true";

/** Fire-and-forget client event. Never throws. */
export function track(event: string, meta?: Record<string, unknown>, handle?: string): void {
  if (!eventsEnabled || typeof window === "undefined") return;
  const body = JSON.stringify({
    events: [{ event, handle, meta }],
  });
  try {
    const url = "/api/events";
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

/** Awaitable so server callers can keep delivery alive with Next's after(). */
export async function logAgentFetch(
  endpoint: string,
  userAgent: string | null | undefined,
  handle?: string,
): Promise<void> {
  if (!eventsEnabled) return;
  const body = JSON.stringify({
    events: [{ event: "agent_fetch", handle, meta: { endpoint } }],
  });
  try {
    await fetch(`${CARDS_API}/events`, {
      method: "POST",
      signal: AbortSignal.timeout(5000),
      headers: {
        "Content-Type": "application/json",
        ...(userAgent ? { "User-Agent": userAgent } : {}),
      },
      body,
      keepalive: true,
    });
  } catch {
    // ignore
  }
}
