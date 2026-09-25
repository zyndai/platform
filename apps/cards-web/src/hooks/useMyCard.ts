"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { getMyCard } from "@/lib/cards";

export function useMyCard() {
  const [ready, setReady] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [handle, setHandle] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const supabase = createClient();

    async function load() {
      try {
        const { data: { session } } = await supabase.auth.getSession();
        if (cancelled) return;
        if (!session?.access_token) {
          setAuthenticated(false);
          setHandle(null);
          setReady(true);
          return;
        }
        setAuthenticated(true);
        const mine = await getMyCard(session.access_token);
        if (cancelled) return;
        setHandle(mine?.handle ?? null);
        setReady(true);
      } catch (err) {
        console.error("[useMyCard] failed:", err);
        if (!cancelled) {
          setHandle(null);
          setReady(true);
        }
      }
    }

    load();
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event) => {
      if (event !== "SIGNED_IN" && event !== "SIGNED_OUT" && event !== "USER_UPDATED") return;
      setReady(false);
      load();
    });
    return () => {
      cancelled = true;
      subscription.unsubscribe();
    };
  }, []);

  return { ready, authenticated, handle };
}
