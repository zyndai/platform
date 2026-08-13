"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui";
import { patchOnboardingMeta } from "@/lib/onboarding";
import { useDashboard } from "@/contexts/DashboardContext";

export default function BriefStep() {
  const router = useRouter();
  const { refreshOnboarding } = useDashboard();
  const [working, setWorking] = useState<"continue" | "skip" | null>(null);

  const handleContinue = async () => {
    setWorking("continue");
    await patchOnboardingMeta({ brief_created: true });
    await refreshOnboarding();
    router.replace("/onboarding/calendar");
  };

  const handleSkip = async () => {
    setWorking("skip");
    await patchOnboardingMeta({ skipped_brief: true });
    await refreshOnboarding();
    router.replace("/onboarding/calendar");
  };

  return (
    <section className="s-brief">
      <h2 className="display-m title">I&apos;ll keep a brief that keeps me current.</h2>
      <p className="copy">
        I&apos;ll keep a running brief about you — what you&apos;re up to, who you&apos;d like
        to meet, what you want to avoid — and re-read it whenever it changes. You can
        edit it any time from your dashboard.
      </p>
      <div className="actions">
        <Button onClick={handleContinue} disabled={working !== null}>
          {working === "continue" ? "One sec…" : "Continue →"}
        </Button>
        <Button variant="tertiary" onClick={handleSkip} disabled={working !== null}>
          {working === "skip" ? "One sec…" : "I'll fill it in later"}
        </Button>
      </div>
      <p className="caption" style={{ marginTop: 24, color: "var(--ink-muted)" }}>
        You&apos;ll find it again under <strong>Your brief</strong> in the sidebar.
      </p>
    </section>
  );
}
