"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Users, Lock, Globe2, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui";
import { getSupabase } from "@/lib/supabase";
import { apiPost, invalidate } from "@/lib/api";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface PublicGroup {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  avatar_url: string | null;
  visibility: "private" | "open";
}

type LoadState =
  | { kind: "loading" }
  | { kind: "ok"; group: PublicGroup; memberCount: number }
  | { kind: "not_found" }
  | { kind: "error"; message: string };

export default function GroupInvitePage() {
  const params = useParams<{ slug: string; token: string }>();
  const router = useRouter();
  const token = params?.token;

  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [signedIn, setSignedIn] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/api/groups/by-invite/${token}`);
        if (cancelled) return;
        if (res.status === 404) {
          setState({ kind: "not_found" });
          return;
        }
        if (!res.ok) {
          setState({ kind: "error", message: await res.text() });
          return;
        }
        const data = await res.json();
        setState({ kind: "ok", group: data.group, memberCount: data.member_count });
      } catch (e) {
        if (cancelled) return;
        setState({ kind: "error", message: e instanceof Error ? e.message : "Couldn't load." });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const sb = getSupabase();
      const { data } = await sb.auth.getSession();
      if (cancelled) return;
      setSignedIn(!!data.session?.user);
      setAuthChecked(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleJoin = useCallback(async () => {
    if (!token) return;
    if (!signedIn) {
      // Send them to sign-in and bounce back to this URL once they're in.
      const redirect = encodeURIComponent(window.location.pathname);
      router.push(`/?next=${redirect}`);
      return;
    }
    setJoining(true);
    setJoinError(null);
    try {
      const data = await apiPost<{ status: string; group_id: string; slug: string }>(
        `/api/groups/by-invite/${token}/join`,
        {},
      );
      invalidate("/api/groups/");
      router.push(`/dashboard/groups/${data.group_id}`);
    } catch (e) {
      setJoinError(e instanceof Error ? e.message : "Couldn't join.");
    } finally {
      setJoining(false);
    }
  }, [token, signedIn, router]);

  return (
    <main className="ppl-shell">
      <div className="ppl-aurora" aria-hidden />
      <div className="ppl-shell-inner">
        {state.kind === "loading" || !authChecked ? (
          <div className="ppl-card ppl-card-loading">
            <div className="ppl-skeleton" style={{ width: 60, height: 60, borderRadius: "50%" }} />
            <div className="ppl-skeleton ppl-skeleton-line" style={{ width: "70%", marginTop: 16 }} />
            <div className="ppl-skeleton ppl-skeleton-line" style={{ width: "50%", marginTop: 8 }} />
          </div>
        ) : state.kind === "not_found" ? (
          <div className="ppl-card ppl-card-empty">
            <h1 className="ppl-name" style={{ fontSize: 24 }}>This invite isn&rsquo;t live.</h1>
            <p className="ppl-empty-sub">
              The link may have been rotated or the group archived. Ask whoever shared it for a fresh link.
            </p>
            <Link href="/" className="ppl-attrib">
              <span>←</span> <strong>Back to Zynd</strong>
            </Link>
          </div>
        ) : state.kind === "error" ? (
          <div className="ppl-card ppl-card-empty">
            <h1 className="ppl-name" style={{ fontSize: 24 }}>Something went wrong.</h1>
            <p className="ppl-error">{state.message}</p>
          </div>
        ) : (
          <div className="ppl-card">
            <div className="ppl-avatar-wrap">
              <div className="ppl-avatar">
                {state.group.avatar_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={state.group.avatar_url} alt="" />
                ) : (
                  <span className="ppl-avatar-initial">
                    {(state.group.name || "?").charAt(0).toUpperCase()}
                  </span>
                )}
              </div>
            </div>

            <span className="ppl-verified">
              <Users size={11} strokeWidth={2} /> Group invite
            </span>
            <h1 className="ppl-name">{state.group.name}</h1>
            <p className="ppl-subline">
              {state.group.visibility === "private" ? (
                <>
                  <Lock size={12} strokeWidth={2} /> Private
                </>
              ) : (
                <>
                  <Globe2 size={12} strokeWidth={2} /> Open
                </>
              )}
              <span className="ppl-dot">·</span>
              <span>
                {state.memberCount} member{state.memberCount === 1 ? "" : "s"}
              </span>
            </p>

            {state.group.description && (
              <p className="ppl-description">{state.group.description}</p>
            )}

            {joinError && <p className="ppl-error">{joinError}</p>}

            <div className="ppl-actions">
              <Button
                onClick={() => void handleJoin()}
                disabled={joining}
                rightIcon={<ArrowRight size={14} strokeWidth={1.8} />}
              >
                {joining
                  ? "Joining…"
                  : signedIn
                    ? "Join group"
                    : "Sign in to join"}
              </Button>
            </div>

            <div className="ppl-trust">
              <Users size={14} strokeWidth={1.7} />
              <span>
                You&rsquo;ll appear to other members by your persona&rsquo;s name and avatar. Group
                content is visible only to members.
              </span>
            </div>

            <Link href="/" className="ppl-attrib">
              <strong>Zynd</strong> <span>·</span> personal AI personas
            </Link>
          </div>
        )}
      </div>
    </main>
  );
}
