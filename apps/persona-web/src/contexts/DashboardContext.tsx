"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { getSupabase } from "@/lib/supabase";
import { type User } from "@supabase/supabase-js";

interface DashboardContextValue {
  user: User | null;
  loading: boolean;
  hasPersona: boolean;
  personaLoading: boolean;
  refreshPersona: () => Promise<void>;
  handleLogout: () => Promise<void>;
}

const DashboardContext = createContext<DashboardContextValue>({
  user: null,
  loading: true,
  hasPersona: false,
  personaLoading: true,
  refreshPersona: async () => {},
  handleLogout: async () => {},
});

export function useDashboard() {
  return useContext(DashboardContext);
}

export function DashboardProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [hasPersona, setHasPersona] = useState(false);
  const [personaLoading, setPersonaLoading] = useState(true);

  const checkPersona = async (userId: string) => {
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/persona/${userId}/status`
      );
      if (res.ok) {
        const data = await res.json();
        setHasPersona(data.deployed === true);
      } else {
        setHasPersona(false);
      }
    } catch {
      setHasPersona(false);
    } finally {
      setPersonaLoading(false);
    }
  };

  const refreshPersona = async () => {
    if (user) {
      setPersonaLoading(true);
      await checkPersona(user.id);
    }
  };

  useEffect(() => {
    const sb = getSupabase();

    const {
      data: { subscription },
    } = sb.auth.onAuthStateChange((event, session) => {
      if (!session) {
        router.replace("/");
      } else {
        setUser(session.user);
        setLoading(false);
      }
    });

    sb.auth.getSession().then(({ data: { session } }) => {
      if (!session) {
        router.replace("/");
      } else {
        setUser(session.user);
        setLoading(false);
      }
    });

    return () => subscription.unsubscribe();
  }, [router]);

  // Check persona status whenever user changes
  useEffect(() => {
    if (user) {
      checkPersona(user.id);
    }
  }, [user]);

  const handleLogout = async () => {
    await getSupabase().auth.signOut();
    router.push("/");
  };

  return (
    <DashboardContext.Provider
      value={{ user, loading, hasPersona, personaLoading, refreshPersona, handleLogout }}
    >
      {children}
    </DashboardContext.Provider>
  );
}
