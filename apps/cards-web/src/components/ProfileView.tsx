"use client";

import { useEffect, useRef } from "react";
import { eventsEnabled, track } from "@/lib/track";

/** Runs on an actual browser mount, never on a server fetch or Link prefetch. */
export function ProfileView({ handle }: { handle: string }) {
  const lastHandle = useRef<string | null>(null);
  useEffect(() => {
    if (!eventsEnabled) return;
    const recordName = () => {
      void fetch("/api/profile-visit", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ handle, visit_id: crypto.randomUUID() }), keepalive: true,
      }).catch(() => undefined);
    };
    if (lastHandle.current !== handle) {
      lastHandle.current = handle;
      track("view", { endpoint: "profile-page" }, handle);
      recordName();
    }
    window.addEventListener("zynd:visitor-privacy-changed", recordName);
    return () => window.removeEventListener("zynd:visitor-privacy-changed", recordName);
  }, [handle]);
  return null;
}
