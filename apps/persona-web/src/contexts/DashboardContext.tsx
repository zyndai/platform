"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { getSupabase } from "@/lib/supabase";
import { type User } from "@supabase/supabase-js";
import {
  computeOnboardingStep,
  readOnboardingMeta,
  type OnboardingStep,
} from "@/lib/onboarding";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface DashboardContextValue {
  user: User | null;
  loading: boolean;
  hasPersona: boolean;
  personaLoading: boolean;
  onboardingStep: OnboardingStep | null;
  onboardingLoading: boolean;
  refreshPersona: () => Promise<void>;
  refreshOnboarding: () => Promise<void>;
  handleLogout: () => Promise<void>;
}

const DashboardContext = createContext<DashboardContextValue>({
  user: null,
  loading: true,
  hasPersona: false,
  personaLoading: true,
  onboardingStep: null,
  onboardingLoading: true,
  refreshPersona: async () => {},
  refreshOnboarding: async () => {},
  handleLogout: async () => {},
});

export function useDashboard() {
  return useContext(DashboardContext);
}

async function fetchCalendarConnected(userId: string, jwt: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/connections/`, {
      headers: { Authorization: `Bearer ${jwt}` },
    });
    if (!res.ok) return false;
    const data = await res.json();
    const scopes: string = data?.connections?.google?.scopes ?? "";
    return scopes.includes("calendar");
  } catch {
    return false;
  }
}

async function fetchHasPersona(userId: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/persona/${userId}/status`);
    if (!res.ok) return false;
    const data = await res.json();
    return data.deployed === true;
  } catch {
    return false;
  }
}

export function DashboardProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const [hasPersona, setHasPersona] = useState(false);
  const [personaLoading, setPersonaLoading] = useState(true);

  const [onboardingStep, setOnboardingStep] = useState<OnboardingStep | null>(null);
  const [onboardingLoading, setOnboardingLoading] = useState(true);

  const recomputeOnboarding = useCallback(
    async (currentUser: User) => {
      setOnboardingLoading(true);
      const sb = getSupabase();
      const { data: { session } } = await sb.auth.getSession();
      const jwt = session?.access_token;

      const [persona, calendar] = await Promise.all([
        fetchHasPersona(currentUser.id),
        jwt ? fetchCalendarConnected(currentUser.id, jwt) : Promise.resolve(false),
      ]);

      setHasPersona(persona);
      setPersonaLoading(false);

      const step = computeOnboardingStep({
        meta: readOnboardingMeta(currentUser),
        hasPersona: persona,
        calendarConnected: calendar,
      });
      setOnboardingStep(step);
      setOnboardingLoading(false);
    },
    [],
  );

  const refreshPersona = useCallback(async () => {
    if (!user) return;
    setPersonaLoading(true);
    await recomputeOnboarding(user);
  }, [user, recomputeOnboarding]);

  const refreshOnboarding = useCallback(async () => {
    if (!user) return;
    // Pull the freshest user so user_metadata.onboarding is current.
    const sb = getSupabase();
    const { data: { user: freshUser } } = await sb.auth.getUser();
    if (freshUser) {
      setUser(freshUser);
      await recomputeOnboarding(freshUser);
    }
  }, [user, recomputeOnboarding]);

  useEffect(() => {
    const sb = getSupabase();
    const {
      data: { subscription },
    } = sb.auth.onAuthStateChange((_event, session) => {
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

  useEffect(() => {
    if (user) {
      void recomputeOnboarding(user);
    }
  }, [user, recomputeOnboarding]);

  const handleLogout = async () => {
    await getSupabase().auth.signOut();
    router.push("/");
  };

  return (
    <DashboardContext.Provider
      value={{
        user,
        loading,
        hasPersona,
        personaLoading,
        onboardingStep,
        onboardingLoading,
        refreshPersona,
        refreshOnboarding,
        handleLogout,
      }}
    >
      {children}
    </DashboardContext.Provider>
  );
}
