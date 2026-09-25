"use client";

/**
 * Session state for cards.zynd.ai — deliberately minimal compared to the
 * dashboard's useAuth: no `developer`/Prisma coupling (that's the dashboard's
 * own product, not ours) and no GitHub login (cards login is Google,
 * LinkedIn, and email magic link only). Ported callers only ever destructure
 * `ready` / `authenticated` / `user`, so that's all this exposes.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { createClient } from "@/lib/supabase/client";
import type { User } from "@supabase/supabase-js";

export interface AuthSnapshot {
  user: User | null;
}

interface AuthContextValue {
  ready: boolean;
  authenticated: boolean;
  user: User | null;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

interface AuthProviderProps {
  initial?: AuthSnapshot;
  children: React.ReactNode;
}

export function AuthProvider({ initial, children }: AuthProviderProps) {
  const supabaseRef = useRef(createClient());
  const supabase = supabaseRef.current;

  const [user, setUser] = useState<User | null>(initial?.user ?? null);
  const [ready, setReady] = useState(!!initial);

  const refresh = useCallback(async () => {
    const { data } = await supabase.auth.getUser();
    setUser(data.user ?? null);
    setReady(true);
  }, [supabase]);

  useEffect(() => {
    if (!initial) refresh();
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      setUser(session?.user ?? null);
      setReady(true);
      void event;
    });
    return () => subscription.unsubscribe();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const logout = useCallback(async () => {
    await supabase.auth.signOut();
    setUser(null);
  }, [supabase]);

  return (
    <AuthContext.Provider value={{ ready, authenticated: !!user, user, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
