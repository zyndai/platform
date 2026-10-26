"use client";

import { useEffect, useRef } from "react";
import { eventsEnabled, track } from "@/lib/track";
import { useAuth } from "@/hooks/useAuth";
import type { SearchRef } from "@/lib/search-link";

const RETRY_DELAYS = [500, 1500];

/** Runs on an actual browser mount, never on a server fetch or Link prefetch. `from` is the search
 *  the visitor came from (its id and the person's rank), counted with the view and then taken out of
 *  the address so a shared link does not carry it. */
export function ProfileView({ handle, from }: { handle: string; from?: SearchRef | null }) {
  const { ready, user } = useAuth();
  const userId = user?.id;
  const lastHandle = useRef<string | null>(null);
  const visit = useRef<{ handle: string; userId: string; id: string } | null>(null);

  useEffect(() => {
    if (!eventsEnabled) return;
    if (lastHandle.current !== handle) {
      lastHandle.current = handle;
      track("view", { endpoint: "profile-page", ...(from ? { search_id: from.searchId, rank: from.rank } : {}) }, handle);
      if (from) {
        try {
          const url = new URL(window.location.href);
          url.searchParams.delete("sid");
          url.searchParams.delete("r");
          window.history.replaceState(window.history.state, "", url);
        } catch { /* a link that cannot be tidied still works */ }
      }
    }
  }, [handle, from]);

  useEffect(() => {
    if (!eventsEnabled || !ready || !userId) return;
    if (visit.current?.handle !== handle || visit.current.userId !== userId) {
      visit.current = { handle, userId, id: crypto.randomUUID() };
    }
    let active = true;
    let generation = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const send = async (id: string, attempt: number, run: number) => {
      let status: number | undefined;
      try {
        const response = await fetch("/api/profile-visit", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ handle, visit_id: id }), keepalive: true,
        });
        status = response.status;
        // A successful response may decline a name because of visitor privacy.
        if (response.ok && status !== 204) {
          const result = await response.json().catch(() => null);
          if (typeof result?.recorded === "boolean") return;
          status = 502;
        } else {
          await response.text();
        }
      } catch { /* Retry a temporary connection failure below. */ }
      if (!active || generation !== run) return;
      const retryable = status === undefined || [204, 401, 408, 429].includes(status) || status >= 500;
      if (retryable && attempt < RETRY_DELAYS.length) {
        timer = setTimeout(() => void send(id, attempt + 1, run), RETRY_DELAYS[attempt]);
      } else {
        console.warn("Profile visit could not be recorded", { status: status ?? "network failure" });
      }
    };

    const recordName = () => {
      clearTimeout(timer);
      const id = visit.current?.id;
      if (id) void send(id, 0, ++generation);
    };
    const privacyChanged = () => {
      // A new consent epoch needs a new ID; retries/focus retain the same ID.
      visit.current = { handle, userId, id: crypto.randomUUID() };
      recordName();
    };
    recordName();
    window.addEventListener("focus", recordName);
    window.addEventListener("zynd:visitor-privacy-changed", privacyChanged);
    return () => {
      active = false;
      clearTimeout(timer);
      window.removeEventListener("focus", recordName);
      window.removeEventListener("zynd:visitor-privacy-changed", privacyChanged);
    };
  }, [handle, ready, userId]);
  return null;
}
