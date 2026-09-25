"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useDashboard } from "@/contexts/DashboardContext";

/**
 * The /dashboard root is just a redirect. If the user hasn't finished
 * onboarding, DashboardShell will intercept the next route and bounce
 * them to /onboarding/<step> before anything renders.
 *
 * One special case: when the OAuth providers redirect back here with a
 * ?oauth=... flag, our cached onboarding state is stale — the token was
 * only just written. Refresh the context before handing off, otherwise
 * the guard can send the user back to the same step they just completed.
 */
export default function DashboardRedirect() {
  const router = useRouter();
  const { refreshOnboarding } = useDashboard();

  useEffect(() => {
    const run = async () => {
      const params = new URLSearchParams(window.location.search);
      if (params.get("oauth")) {
        await refreshOnboarding();
      }
      router.replace("/dashboard/chat");
    };
    void run();
  }, [router, refreshOnboarding]);

  return null;
}
