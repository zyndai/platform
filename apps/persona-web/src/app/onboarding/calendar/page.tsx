"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Calendar, Shield } from "lucide-react";
import { Button, Card } from "@/components/ui";
import { getSupabase } from "@/lib/supabase";
import { patchOnboardingMeta } from "@/lib/onboarding";
import { useDashboard } from "@/contexts/DashboardContext";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function CalendarStep() {
  const router = useRouter();
  const { refreshOnboarding } = useDashboard();
  const [working, setWorking] = useState<"connect" | "skip" | null>(null);

  const connect = async () => {
    setWorking("connect");
    const sb = getSupabase();
    const {
      data: { session },
    } = await sb.auth.getSession();
    const jwt = session?.access_token;
    if (!jwt) {
      setWorking(null);
      return;
    }
    // Always request both scopes — Google's token rotation would wipe the
    // brief's `docs` scope if we re-authed for calendar only.
    const url = `${API_BASE}/api/oauth/google/authorize?features=calendar,docs&token=${encodeURIComponent(jwt)}`;
    window.location.href = url;
  };

  const skip = async () => {
    setWorking("skip");
    await patchOnboardingMeta({ skipped_calendar: true });
    await refreshOnboarding();
    router.replace("/onboarding/matches");
  };

  return (
    <section className="s-calendar">
      <Card className="cal-card">
        <Calendar className="cal-icon" strokeWidth={1.5} size={32} />
        <h2 className="display-s" style={{ marginBottom: 12 }}>
          One more thing — when are you free?
        </h2>
        <p className="body secondary" style={{ marginBottom: 20 }}>
          I need calendar access so I can offer real meeting times instead of
          &ldquo;let me check and get back to you.&rdquo;
        </p>
        <Button fullWidth onClick={connect} disabled={working !== null}>
          {working === "connect" ? "Opening Google…" : "Let Aria see when I'm free"}
        </Button>
        <div className="trust">
          <Shield />
          <span>
            I only see busy and free blocks. I never see what your meetings are about.
          </span>
        </div>
        <div style={{ marginTop: 16, textAlign: "center" }}>
          <Button variant="tertiary" onClick={skip} disabled={working !== null}>
            {working === "skip" ? "One sec…" : "I'll do this later"}
          </Button>
        </div>
      </Card>
    </section>
  );
}
