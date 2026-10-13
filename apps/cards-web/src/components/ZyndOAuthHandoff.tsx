"use client";

import { useEffect, useRef } from "react";
import { createClient } from "@/lib/supabase/client";
import { startLinkedInOAuth } from "@/lib/auth/session";
import { captureZyndOAuthReq, completeZyndOAuth, hasPendingZyndOAuth } from "@/lib/zynd-oauth";

export function ZyndOAuthHandoff() {
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    captureZyndOAuthReq();
    if (!hasPendingZyndOAuth()) return;

    const path = window.location.pathname;
    if (path === "/auth" || path.startsWith("/auth/")) return;

    void (async () => {
      const { data: { session } } = await createClient().auth.getSession();
      if (session?.access_token && await completeZyndOAuth(session.access_token)) return;
      if (!session) await startLinkedInOAuth(`${path}${window.location.search}`);
    })();
  }, []);

  return null;
}
