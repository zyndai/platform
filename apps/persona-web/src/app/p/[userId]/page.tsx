"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Sparkles, Send, Copy, Check, MapPin, Briefcase } from "lucide-react";
import { Button } from "@/components/ui";
import { getSupabase } from "@/lib/supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface PublicPersona {
  name: string;
  agent_id: string;
  agent_handle?: string | null;
  description: string;
  capabilities: string[];
  avatar_url?: string | null;
  title?: string | null;
  organization?: string | null;
  location?: string | null;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "ok"; persona: PublicPersona }
  | { kind: "not_found" }
  | { kind: "error"; message: string };

export default function PublicPersonaPage() {
  const params = useParams<{ userId: string }>();
  const userId = params?.userId;
  const router = useRouter();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [authChecked, setAuthChecked] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [myUserId, setMyUserId] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/api/persona/${userId}/public`);
        if (cancelled) return;
        if (res.status === 404) {
          setState({ kind: "not_found" });
          return;
        }
        if (!res.ok) {
          setState({ kind: "error", message: await res.text() });
          return;
        }
        const persona = (await res.json()) as PublicPersona;
        setState({ kind: "ok", persona });
      } catch (e) {
        if (cancelled) return;
        setState({
          kind: "error",
          message: e instanceof Error ? e.message : "Couldn't load this persona.",
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const sb = getSupabase();
        const {
          data: { session },
        } = await sb.auth.getSession();
        if (cancelled) return;
        if (session?.user?.id) {
          setSignedIn(true);
          setMyUserId(session.user.id);
        }
      } catch {
        /* anonymous viewer */
      } finally {
        if (!cancelled) setAuthChecked(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleConnect = useCallback(async () => {
    if (state.kind !== "ok") return;
    if (!signedIn || !myUserId) {
      router.push(`/?next=/p/${userId}`);
      return;
    }
    if (myUserId === userId) {
      router.push("/dashboard");
      return;
    }
    setConnecting(true);
    setConnectError(null);
    try {
      const sb = getSupabase();
      const {
        data: { session },
      } = await sb.auth.getSession();
      const jwt = session?.access_token;
      if (!jwt) {
        router.push(`/?next=/p/${userId}`);
        return;
      }
      const res = await fetch(`${API}/api/persona/${myUserId}/threads`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${jwt}`,
        },
        body: JSON.stringify({
          target_agent_id: state.persona.agent_id,
          target_name: state.persona.name || "Network Agent",
          mode: "agent",
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const tid = data?.thread?.id as string | undefined;
      router.push(tid ? `/dashboard/messages?thread=${tid}` : "/dashboard/messages");
    } catch (e) {
      setConnectError(e instanceof Error ? e.message : "Couldn't start the conversation.");
    } finally {
      setConnecting(false);
    }
  }, [state, signedIn, myUserId, userId, router]);

  const handleShare = useCallback(async () => {
    if (typeof window === "undefined") return;
    const url = window.location.href;
    try {
      if (navigator.share) {
        await navigator.share({ url, title: cardTitle(state) });
        return;
      }
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      /* user cancelled */
    }
  }, [state]);

  if (state.kind === "loading") {
    return (
      <PublicShell>
        <div className="ppl-card ppl-card-loading">
          <div className="ppl-avatar ppl-skeleton" />
          <div className="ppl-skeleton ppl-skeleton-line" style={{ width: 180 }} />
          <div className="ppl-skeleton ppl-skeleton-line" style={{ width: 260 }} />
        </div>
      </PublicShell>
    );
  }

  if (state.kind === "not_found") {
    return (
      <PublicShell>
        <div className="ppl-card ppl-card-empty">
          <h1 className="ppl-name">No agent here.</h1>
          <p className="ppl-empty-sub">
            The link is stale, or this persona was retired.
          </p>
          <Link href="/" style={{ textDecoration: "none" }}>
            <Button>Claim your ZyndAI agent →</Button>
          </Link>
        </div>
      </PublicShell>
    );
  }

  if (state.kind === "error") {
    return (
      <PublicShell>
        <div className="ppl-card ppl-card-empty">
          <h1 className="ppl-name">Couldn&apos;t load this page.</h1>
          <p className="ppl-empty-sub">{state.message}</p>
        </div>
      </PublicShell>
    );
  }

  const { persona } = state;
  const firstName = persona.name?.split(" ")[0] || "this agent";
  const introLine = persona.agent_handle
    ? `${persona.agent_handle} — agent of record for ${persona.name}.`
    : `Agent of record for ${persona.name}.`;
  const ctaLabel = !authChecked
    ? "Connect with my agent"
    : !signedIn
      ? "Sign in to connect"
      : myUserId === userId
        ? "Open your dashboard →"
        : `Message ${firstName} →`;
  const subline = [persona.title, persona.organization].filter(Boolean).join(" · ");

  return (
    <PublicShell>
      <div className="ppl-card">
        <PersonaAvatar
          src={persona.avatar_url}
          name={persona.name}
          agentId={persona.agent_id}
        />
        <div className="ppl-verified" aria-label="Verified on ZyndAI">
          <Sparkles size={12} strokeWidth={2} />
          <span>Verified on ZyndAI</span>
        </div>
        <h1 className="ppl-name">{persona.name}</h1>
        {subline && <p className="ppl-subline">
          {persona.title && <><Briefcase size={12} strokeWidth={1.8} /> {persona.title}</>}
          {persona.title && persona.organization && <span className="ppl-dot">·</span>}
          {persona.organization && <span>{persona.organization}</span>}
        </p>}
        {persona.location && (
          <p className="ppl-location"><MapPin size={12} strokeWidth={1.8} /> {persona.location}</p>
        )}

        <p className="ppl-intro">{introLine}</p>

        {persona.description && (
          <p className="ppl-description">{persona.description}</p>
        )}

        {persona.capabilities.length > 0 && (
          <div className="ppl-caps">
            {persona.capabilities.slice(0, 8).map((c) => (
              <span key={c} className="ppl-cap">{c}</span>
            ))}
          </div>
        )}

        <div className="ppl-actions">
          <Button
            onClick={handleConnect}
            disabled={connecting}
            rightIcon={<Send size={14} strokeWidth={2} />}
          >
            {connecting ? "Starting…" : ctaLabel}
          </Button>
          <button
            type="button"
            className="ppl-share-btn"
            onClick={handleShare}
            aria-label="Copy share link"
          >
            {copied ? (
              <>
                <Check size={14} strokeWidth={2} /> Copied
              </>
            ) : (
              <>
                <Copy size={14} strokeWidth={2} /> Share
              </>
            )}
          </button>
        </div>

        {connectError && <p className="ppl-error">{connectError}</p>}

        <div className="ppl-trust">
          <Sparkles size={12} strokeWidth={2} />
          <span>
            Briefs reach {firstName}. Cold DMs don&apos;t.
          </span>
        </div>
      </div>

      <Link href="/" className="ppl-attrib">
        Built on <strong>ZyndAI</strong> <span aria-hidden>·</span> Claim your agent →
      </Link>
    </PublicShell>
  );
}

function PersonaAvatar({
  src,
  name,
  agentId,
}: {
  src?: string | null;
  name?: string | null;
  agentId?: string;
}) {
  const [errored, setErrored] = useState(false);
  // Some Google CDN avatars 403 when hot-linked with default sizes — bumping
  // the size param often resolves it and produces a higher-res image too.
  const normalized = useMemo(() => normalizeAvatar(src), [src]);
  const showImg = !!normalized && !errored;
  const initial = (name?.trim() || "?")[0]?.toUpperCase() ?? "?";
  // Stable hue per agent so initial backgrounds aren't all the same.
  const hue = useMemo(() => hashHue(agentId || name || ""), [agentId, name]);

  return (
    <div className="ppl-avatar-wrap">
      <div
        className="ppl-avatar"
        style={{
          background: showImg
            ? "var(--surface-raised)"
            : `linear-gradient(135deg, hsl(${hue} 70% 62%), hsl(${(hue + 36) % 360} 70% 55%))`,
        }}
      >
        {showImg ? (
          <img
            src={normalized!}
            alt={name ?? ""}
            referrerPolicy="no-referrer"
            onError={() => setErrored(true)}
          />
        ) : (
          <span className="ppl-avatar-initial" aria-hidden>{initial}</span>
        )}
      </div>
    </div>
  );
}

function normalizeAvatar(url: string | null | undefined): string | null {
  if (!url) return null;
  // Google "s96-c" / "=s96-c" sizing param — bump to 256 for the hero.
  return url
    .replace(/=s\d+-c$/, "=s256-c")
    .replace(/\/s\d+-c\//, "/s256-c/");
}

function hashHue(input: string): number {
  let h = 0;
  for (let i = 0; i < input.length; i++) {
    h = (h * 31 + input.charCodeAt(i)) & 0xffffffff;
  }
  return Math.abs(h) % 360;
}

function cardTitle(state: LoadState): string {
  if (state.kind === "ok") return `${state.persona.name} · Zynd Persona`;
  return "Zynd Persona";
}

function PublicShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="ppl-shell">
      <div className="ppl-aurora" aria-hidden />
      <div className="ppl-shell-inner">{children}</div>
    </div>
  );
}
