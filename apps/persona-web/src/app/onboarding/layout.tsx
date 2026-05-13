"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { DashboardProvider, useDashboard } from "@/contexts/DashboardContext";
import { BootLoader, Monogram, type BootStage } from "@/components/ui";

// Steps where "Edit later" in the topbar doesn't make sense (user would
// just be bounced back here). On those, show nothing on the right side.
const STEPS_WITH_NO_SKIP = new Set([
  "/onboarding/reading",
  "/onboarding/you",
  "/onboarding/matches",
]);

function OnboardingShell({ children }: { children: React.ReactNode }) {
  const { user, loading, onboardingStep, onboardingLoading, personaLoading } = useDashboard();
  const router = useRouter();
  const pathname = usePathname();
  const showSkip = !STEPS_WITH_NO_SKIP.has(pathname);

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/");
    }
    if (
      !loading &&
      !onboardingLoading &&
      onboardingStep === "done"
    ) {
      router.replace("/dashboard/chat");
    }
  }, [loading, user, onboardingLoading, onboardingStep, router]);

  const stillBooting =
    loading || onboardingLoading || !user || onboardingStep === "done";

  if (stillBooting) {
    let stage: BootStage = "signin";
    if (!loading && user) {
      if (personaLoading) stage = "persona";
      else if (onboardingLoading) stage = "accounts";
      else stage = "ready";
    }
    return <BootLoader stage={stage} />;
  }

  return (
    <div className="onboarding-shell">
      <div className="onboarding-topbar">
        <div className="brand">
          <Monogram size="sm" />
          <span className="brand-text">ZyndAI Persona</span>
        </div>
        {showSkip ? (
          <Link href="/dashboard/chat" className="skip-link">
            Edit later
          </Link>
        ) : (
          <span />
        )}
      </div>
      <div className="onboarding-content">{children}</div>
    </div>
  );
}

export default function OnboardingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <DashboardProvider>
      <OnboardingShell>{children}</OnboardingShell>
    </DashboardProvider>
  );
}
