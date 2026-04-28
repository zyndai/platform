"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, ThinkingDot } from "@/components/ui";
import { useDashboard } from "@/contexts/DashboardContext";
import MatchCard from "@/components/chat/MatchCard";
import IntroPreviewModal from "@/components/chat/IntroPreviewModal";
import type { PersonaHit } from "@/components/chat/types";
import { getSupabase } from "@/lib/supabase";
import { patchOnboardingMeta } from "@/lib/onboarding";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Match {
  agent_id: string;
  name: string;
  description: string;
  headline: string;
  recent_post: string | null;
  reason: string;
}

export default function MatchesStep() {
  const router = useRouter();
  const { user, refreshOnboarding } = useDashboard();

  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<"continue" | "more" | null>(null);
  const [seenIds, setSeenIds] = useState<Set<string>>(new Set());
  const [introTarget, setIntroTarget] = useState<PersonaHit | null>(null);
  const [myPersonaName, setMyPersonaName] = useState("");

  const loadMatches = useCallback(
    async (excluded: Set<string>) => {
      if (!user) return;
      setLoading(true);
      try {
        const params = new URLSearchParams({ limit: "3" });
        if (excluded.size > 0) {
          params.set("exclude", Array.from(excluded).join(","));
        }
        const res = await fetch(`${API}/api/matches/${user.id}?${params}`);
        if (res.ok) {
          const data = await res.json();
          setMatches(data.matches || []);
        }
      } finally {
        setLoading(false);
      }
    },
    [user],
  );

  useEffect(() => {
    void loadMatches(seenIds);
    // Intentional: only load on mount; "Show me more" calls loadMatches directly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Pull the user's persona name once for the intro draft signature.
  useEffect(() => {
    if (!user) return;
    fetch(`${API}/api/persona/${user.id}/status`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.deployed && typeof d.name === "string") setMyPersonaName(d.name);
      })
      .catch(() => {});
  }, [user]);

  const showMore = async () => {
    setWorking("more");
    const next = new Set(seenIds);
    matches.forEach((m) => next.add(m.agent_id));
    setSeenIds(next);
    await loadMatches(next);
    setWorking(null);
  };

  const finishOnboarding = async () => {
    setWorking("continue");
    await patchOnboardingMeta({ matches_shown: true });
    await refreshOnboarding();
    router.replace("/dashboard/chat");
  };

  // Same intro flow as the home chat: create agent-mode thread, send the
  // first message, jump into Home where the conversation continues.
  const sendIntro = async (message: string): Promise<string> => {
    if (!user || !introTarget) throw new Error("Missing context");
    const tRes = await fetch(`${API}/api/persona/${user.id}/threads`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target_agent_id: introTarget.agent_id,
        target_name: introTarget.name || "Network Agent",
        mode: "agent",
      }),
    });
    if (!tRes.ok) throw new Error(await tRes.text());
    const tid = (await tRes.json())?.thread?.id as string | undefined;
    if (!tid) throw new Error("Couldn't open the thread.");
    const sRes = await fetch(`${API}/api/persona/${user.id}/agent-send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: tid, content: message }),
    });
    if (!sRes.ok) throw new Error(await sRes.text());
    return tid;
  };

  const onIntroSent = async () => {
    setIntroTarget(null);
    await patchOnboardingMeta({ matches_shown: true });
    await refreshOnboarding();
    router.replace("/dashboard/chat");
  };

  if (loading) {
    return (
      <section className="s-matches">
        <div className="stage" style={{ textAlign: "center" }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
            <ThinkingDot />
            <span className="body-l">Lining up your first three…</span>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="s-matches">
      <div className="stage" style={{ maxWidth: 720, width: "100%" }}>
        {matches.length > 0 ? (
          <>
            <h2 className="display-m title">Three people I think you&apos;d want to meet.</h2>
            <p className="body-l subtitle">
              Specific reasons below. If none click, tell me and I&apos;ll keep looking.
            </p>

            <div className="onboarding-matches">
              {matches.map((m) => (
                <MatchCard
                  key={m.agent_id}
                  hit={{
                    agent_id: m.agent_id,
                    name: m.name,
                    description: m.description,
                  }}
                  headline={m.headline}
                  pullQuote={m.recent_post || undefined}
                  reason={m.reason}
                  onSayHi={() =>
                    setIntroTarget({
                      agent_id: m.agent_id,
                      name: m.name,
                      description: m.description,
                    })
                  }
                />
              ))}
            </div>

            <div className="match-actions-row">
              <button
                type="button"
                className="text-link"
                onClick={showMore}
                disabled={working !== null}
              >
                {working === "more" ? "Looking again…" : "Not the right three? Show me more."}
              </button>
              <Button
                variant="secondary"
                onClick={finishOnboarding}
                disabled={working !== null}
              >
                {working === "continue" ? "One sec…" : "These are good, continue →"}
              </Button>
            </div>
          </>
        ) : (
          <div style={{ textAlign: "center" }}>
            <h2 className="display-s title" style={{ marginBottom: 12 }}>
              I&apos;m having trouble finding the right people on your first day.
            </h2>
            <p className="body secondary" style={{ marginBottom: 24 }}>
              Give me another few hours and I&apos;ll come back to you. Meanwhile, open
              your brief and tell me a bit more about who you&apos;d like to meet.
            </p>
            <Button onClick={finishOnboarding} disabled={working !== null}>
              {working === "continue" ? "One sec…" : "Take me to my home →"}
            </Button>
          </div>
        )}
      </div>

      {introTarget && (
        <IntroPreviewModal
          target={introTarget}
          myName={myPersonaName}
          onClose={() => setIntroTarget(null)}
          onSent={onIntroSent}
          send={sendIntro}
        />
      )}
    </section>
  );
}
