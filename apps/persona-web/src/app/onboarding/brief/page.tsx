"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui";
import { patchOnboardingMeta, readOnboardingMeta } from "@/lib/onboarding";
import { useDashboard } from "@/contexts/DashboardContext";
import { getSupabase } from "@/lib/supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function postCreateBrief(): Promise<
  | { ok: true; doc_url: string }
  | { ok: false; needsScope: boolean; message: string }
> {
  const sb = getSupabase();
  const {
    data: { session },
  } = await sb.auth.getSession();
  const jwt = session?.access_token;
  if (!jwt) return { ok: false, needsScope: false, message: "Not signed in" };

  const res = await fetch(`${API}/api/brief/create`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${jwt}`,
    },
    body: JSON.stringify({}),
  });
  if (res.ok) {
    const data = await res.json();
    return { ok: true, doc_url: data.url };
  }
  if (res.status === 403) {
    let detail: { code?: string; message?: string } = {};
    try {
      detail = (await res.json()).detail || {};
    } catch {
      /* fallthrough */
    }
    if (detail?.code === "drive_scope_needed") {
      return {
        ok: false,
        needsScope: true,
        message: detail?.message || "Need Drive access.",
      };
    }
  }
  return {
    ok: false,
    needsScope: false,
    message: (await res.text().catch(() => "")) || `HTTP ${res.status}`,
  };
}

export default function BriefStep() {
  const router = useRouter();
  const { user, refreshOnboarding } = useDashboard();
  const [working, setWorking] = useState<"create" | "skip" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ranAutoOnce = useRef(false);

  // Resume case: we set `pending_brief_create=true` right before redirecting
  // to Google OAuth. When the user lands back here after granting scope,
  // auto-fire the create and advance — so the OAuth detour feels seamless.
  useEffect(() => {
    if (!user || ranAutoOnce.current) return;
    const meta = readOnboardingMeta(user);
    if (!meta.pending_brief_create) return;
    ranAutoOnce.current = true;

    void (async () => {
      setWorking("create");
      const result = await postCreateBrief();
      if (result.ok) {
        await patchOnboardingMeta({
          pending_brief_create: false,
          brief_created: true,
        });
        await refreshOnboarding();
        router.replace("/onboarding/calendar");
      } else {
        // Clear the flag so we don't loop. Surface the error to the user
        // and let them retry or skip from the buttons below.
        await patchOnboardingMeta({ pending_brief_create: false });
        setError(result.message);
        setWorking(null);
      }
    })();
  }, [user, refreshOnboarding, router]);

  const handleCreate = async () => {
    setWorking("create");
    setError(null);
    const result = await postCreateBrief();
    if (result.ok) {
      await patchOnboardingMeta({ brief_created: true });
      await refreshOnboarding();
      router.replace("/onboarding/calendar");
      return;
    }
    if (result.needsScope) {
      // Hand off to Google OAuth. Always request both scopes so the
      // calendar step doesn't have to also dance — Google's token rotation
      // would otherwise wipe whichever scope wasn't requested second.
      const sb = getSupabase();
      const {
        data: { session },
      } = await sb.auth.getSession();
      if (!session?.access_token) {
        setError("Not signed in.");
        setWorking(null);
        return;
      }
      await patchOnboardingMeta({ pending_brief_create: true });
      window.location.href =
        `${API}/api/oauth/google/authorize?features=calendar,docs&token=${session.access_token}`;
      return;
    }
    setError(result.message);
    setWorking(null);
  };

  const handleSkip = async () => {
    setWorking("skip");
    await patchOnboardingMeta({ skipped_brief: true });
    await refreshOnboarding();
    router.replace("/onboarding/calendar");
  };

  return (
    <section className="s-brief">
      <h2 className="display-m title">
        I&apos;ll keep a doc in your Drive that keeps me current.
      </h2>
      <p className="copy">
        I&apos;ll create a doc called &ldquo;My brief — for Aria&rdquo; in your Google Drive.
        You jot down what you&apos;re up to, who you&apos;d like to meet, what you want to avoid.
        I&apos;ll re-read it whenever it changes. You own the doc — open it any time.
      </p>
      {error && (
        <p className="body-s" style={{ color: "var(--danger)", marginBottom: 16, maxWidth: 540 }}>
          {error}
        </p>
      )}
      <div className="actions">
        <Button onClick={handleCreate} disabled={working !== null}>
          {working === "create" ? "Creating…" : "Create my brief →"}
        </Button>
        <Button variant="tertiary" onClick={handleSkip} disabled={working !== null}>
          {working === "skip" ? "One sec…" : "I'll fill it in later"}
        </Button>
      </div>
      <p className="caption" style={{ marginTop: 24, color: "var(--ink-muted)" }}>
        I&apos;ll never read anything else in your Drive.
      </p>
    </section>
  );
}
