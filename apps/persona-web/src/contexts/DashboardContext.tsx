"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { getSupabase } from "@/lib/supabase";
import { type User } from "@supabase/supabase-js";

interface DashboardContextValue {
  user: User | null;
  loading: boolean;
  handleLogout: () => Promise<void>;
}

const DashboardContext = createContext<DashboardContextValue>({
  user: null,
  loading: true,
  handleLogout: async () => {},
});

export function useDashboard() {
  return useContext(DashboardContext);
}

export function DashboardProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

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

  const handleLogout = async () => {
    await getSupabase().auth.signOut();
    router.push("/");
  };

  return (
    <DashboardContext.Provider value={{ user, loading, handleLogout }}>
      {children}
    </DashboardContext.Provider>
  );
}
