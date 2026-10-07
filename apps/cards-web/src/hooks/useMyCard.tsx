"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { getMyCard, type AgentProfileCard } from "@/lib/cards";

/**
 * "Which card belongs to the signed-in visitor?" — resolved on the server
 * during SSR and shared through context so the Navbar, landing hero and
 * profile header all paint with the answer immediately instead of waiting
 * for a post-hydration session lookup + /cards/mine round-trip.
 */

export interface MyCardSnapshot {
  authenticated: boolean;
  handle: string | null;
  card: AgentProfileCard | null;
}

export interface MyCardValue extends MyCardSnapshot {
  ready: boolean;
  refresh: () => Promise<void>;
}

const MyCardContext = createContext<MyCardValue | null>(null);

export function MyCardProvider({
  initial,
  children,
}: {
  initial?: MyCardSnapshot | null;
  children: React.ReactNode;
}) {
  const [snap, setSnap] = useState<MyCardSnapshot>(
    initial ?? { authenticated: false, handle: null, card: null },
  );
  const [ready, setReady] = useState(Boolean(initial));

  const refresh = useCallback(async () => {
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) {
        setSnap({ authenticated: false, handle: null, card: null });
        setReady(true);
        return;
      }
      const mine = await getMyCard(session.access_token);
      setSnap({ authenticated: true, handle: mine?.handle ?? null, card: mine?.card ?? null });
    } catch (err) {
      console.error("[useMyCard] failed:", err);
      setSnap((prev) => ({ authenticated: prev.authenticated, handle: null, card: null }));
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    // Initial snapshot missing (client-only render): resolve on the next
    // tick so the SSR-painted state isn't thrown away synchronously.
    if (!initial) timer = setTimeout(() => void refresh(), 0);
    const supabase = createClient();
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event) => {
      if (event !== "SIGNED_IN" && event !== "SIGNED_OUT" && event !== "USER_UPDATED") return;
      setReady(false);
      void refresh();
    });
    return () => {
      if (timer) clearTimeout(timer);
      subscription.unsubscribe();
    };
  }, [initial, refresh]);

  return (
    <MyCardContext.Provider value={{ ...snap, ready, refresh }}>
      {children}
    </MyCardContext.Provider>
  );
}

/** Provider-less fallback (client-only resolution), same behaviour as before the SSR snapshot. */
function useStandaloneMyCard(): MyCardValue {
  const [snap, setSnap] = useState<MyCardSnapshot>({ authenticated: false, handle: null, card: null });
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) {
        setSnap({ authenticated: false, handle: null, card: null });
        setReady(true);
        return;
      }
      const mine = await getMyCard(session.access_token);
      setSnap({ authenticated: true, handle: mine?.handle ?? null, card: mine?.card ?? null });
    } catch (err) {
      console.error("[useMyCard] failed:", err);
      setSnap({ authenticated: false, handle: null, card: null });
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void refresh(), 0);
    const supabase = createClient();
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event) => {
      if (event !== "SIGNED_IN" && event !== "SIGNED_OUT" && event !== "USER_UPDATED") return;
      setReady(false);
      void refresh();
    });
    return () => {
      clearTimeout(timer);
      subscription.unsubscribe();
    };
  }, [refresh]);

  return { ...snap, ready, refresh };
}

export function useMyCard(): MyCardValue {
  const ctx = useContext(MyCardContext);
  if (ctx) return ctx;
  // eslint-disable-next-line react-hooks/rules-of-hooks
  return useStandaloneMyCard();
}