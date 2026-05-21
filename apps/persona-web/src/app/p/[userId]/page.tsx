"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowRight,
  BadgeCheck,
  Briefcase,
  CalendarDays,
  Check,
  ChevronLeft,
  Copy,
  Link as LinkIcon,
  MessageCircle,
  MoreHorizontal,
  Send,
  ShieldCheck,
  X,
} from "lucide-react";
import { Button } from "@/components/ui";
import { QrCode as QrCodeImage } from "@/components/QrCode";
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
  const [shareOpen, setShareOpen] = useState(false);

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

  const shareUrl = useCallback(() => {
    if (typeof window === "undefined") return "";
    return window.location.href;
  }, []);

  const handleCopy = useCallback(async () => {
    const url = shareUrl();
    if (!url) return;
    await navigator.clipboard.writeText(url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }, [shareUrl]);

  const handleNativeShare = useCallback(async () => {
    const url = shareUrl();
    if (!url) return;
    try {
      if (navigator.share) {
        await navigator.share({ url, title: cardTitle(state) });
        return;
      }
      await handleCopy();
    } catch {
      /* user cancelled */
    }
  }, [handleCopy, shareUrl, state]);

  if (state.kind === "loading") {
    return (
      <PublicShell>
        <div className="public-loading-card">
          <div className="public-skeleton public-skeleton-avatar" />
          <div className="public-skeleton public-skeleton-line" />
          <div className="public-skeleton public-skeleton-line short" />
        </div>
      </PublicShell>
    );
  }

  if (state.kind === "not_found") {
    return (
      <PublicShell>
        <div className="public-empty-card">
          <h1>No card here.</h1>
          <p>The link is stale, or this persona was retired.</p>
          <Link href="/" style={{ textDecoration: "none" }}>
            <Button>Claim your ZyndAI agent</Button>
          </Link>
        </div>
      </PublicShell>
    );
  }

  if (state.kind === "error") {
    return (
      <PublicShell>
        <div className="public-empty-card">
          <h1>Couldn&apos;t load this page.</h1>
          <p>{state.message}</p>
        </div>
      </PublicShell>
    );
  }

  const { persona } = state;
  const firstName = persona.name?.split(" ")[0] || "this agent";
  // The card belongs to the principal — label the in-card chat row as
  // "Chat with <FirstName>'s persona" so the viewer knows whose agent
  // they're about to talk to.
  const personaLabel = `${firstName}'s persona`;
  const handle = slugifyHandle(persona.agent_handle || persona.name || userId || "you");
  const subline = buildSubline(persona);
  const bio = persona.description?.trim() || "";
  // Real shareable URL — current host + this page's path. Used for the
  // copy bar, the QR target, and the native share sheet.
  const publicHref = typeof window !== "undefined" && userId
    ? new URL(`/p/${userId}`, window.location.origin).toString()
    : "";
  // Compact display form: hostname + abbreviated user id.
  const publicUrl = typeof window !== "undefined" && userId
    ? `${window.location.host}/p/${String(userId).slice(0, 8)}`
    : "your card";
  const canConnect = authChecked && signedIn && myUserId !== userId;

  return (
    <PublicShell>
      <main className="public-card-screen">
        <nav className="public-card-nav" aria-label="Card controls">
          <button type="button" onClick={() => router.back()} aria-label="Back">
            <ChevronLeft size={22} strokeWidth={1.8} />
          </button>
          <span>Your card</span>
          <button type="button" onClick={() => setShareOpen(true)} aria-label="More">
            <MoreHorizontal size={22} strokeWidth={1.8} />
          </button>
        </nav>

        <section className="public-full-card">
          <div className="public-card-brand-row">
            <span>persona</span>
            <span className="public-verified">
              <BadgeCheck size={14} strokeWidth={2} />
              Verified
            </span>
          </div>
          <PublicAvatar src={persona.avatar_url} name={persona.name} agentId={persona.agent_id} />
          <h1>{persona.name}</h1>
          {subline && <p className="public-card-role">{subline}</p>}
          {bio && <p className="public-card-bio">&quot;{bio}&quot;</p>}
          <div className="public-card-chat-row">
            <span className="public-agent-orb" aria-hidden />
            <div>
              <strong>Chat with {personaLabel}</strong>
              <span>Ask about my work - book time</span>
            </div>
            <button
              type="button"
              onClick={handleConnect}
              disabled={connecting}
              aria-label={canConnect ? `Message ${firstName}` : "Open conversation"}
            >
              <ArrowRight size={22} strokeWidth={2.2} />
            </button>
          </div>
        </section>

        <div className="public-link-row">
          <span>{publicUrl}</span>
          <button type="button" onClick={handleCopy}>
            {copied ? <Check size={16} strokeWidth={2} /> : <Copy size={16} strokeWidth={2} />}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>

        <section className="public-quick-actions">
          <p className="public-kicker">Quick actions</p>
          <div className="public-quick-grid">
            <button
              type="button"
              onClick={handleConnect}
              disabled={connecting}
              aria-label={`Book a call with ${firstName}`}
            >
              <span><CalendarDays size={22} strokeWidth={2} /></span>
              <strong>Book a call</strong>
              <em>Find a slot together</em>
            </button>
            <button
              type="button"
              onClick={handleConnect}
              disabled={connecting}
              aria-label={`Send ${firstName} a message`}
            >
              <span><MessageCircle size={22} strokeWidth={2} /></span>
              <strong>Send a message</strong>
              <em>Start a thread</em>
            </button>
            <button
              type="button"
              onClick={handleConnect}
              disabled={connecting}
              aria-label={`See what ${firstName} is working on`}
            >
              <span><Briefcase size={22} strokeWidth={2} /></span>
              <strong>View work</strong>
              <em>Ask the persona anything</em>
            </button>
          </div>
        </section>

        {connectError && <p className="public-card-error">{connectError}</p>}
      </main>

      {shareOpen && (
        <ShareSheet
          persona={persona}
          publicHref={publicHref}
          publicUrl={publicUrl}
          personaLabel={personaLabel}
          copied={copied}
          onCopy={handleCopy}
          onShare={handleNativeShare}
          onClose={() => setShareOpen(false)}
        />
      )}
    </PublicShell>
  );
}

function ShareSheet({
  persona,
  publicHref,
  publicUrl,
  personaLabel,
  copied,
  onCopy,
  onShare,
  onClose,
}: {
  persona: PublicPersona;
  publicHref: string;
  publicUrl: string;
  personaLabel: string;
  copied: boolean;
  onCopy: () => void;
  onShare: () => void;
  onClose: () => void;
}) {
  return (
    <div className="public-share-scrim" role="dialog" aria-modal="true" aria-label="Share your card">
      <div className="public-share-backdrop" aria-hidden />
      <section className="public-share-sheet">
        <span className="public-sheet-grabber" aria-hidden />
        <button type="button" className="public-sheet-close" onClick={onClose} aria-label="Close">
          <X size={18} strokeWidth={2.2} />
        </button>
        <h2>Share your card</h2>
        <p>Scan the code, or use the link below.</p>
        <div className="public-share-mini-card">
          <PublicAvatar src={persona.avatar_url} name={persona.name} agentId={persona.agent_id} small />
          <div>
            <strong>{persona.name}</strong>
            <span>{publicUrl}</span>
          </div>
          {publicHref ? <QrCodeImage value={publicHref} size={96} /> : <span aria-hidden />}
        </div>
        <div className="public-copy-bar">
          <LinkIcon size={16} strokeWidth={2} />
          <span>{publicUrl}</span>
          <button type="button" onClick={onCopy}>{copied ? "Copied" : "Copy"}</button>
        </div>
        <button type="button" className="public-share-native" onClick={onShare}>
          <Send size={18} strokeWidth={2} />
          Share via system
        </button>
        <div className="public-sheet-note">
          <ShieldCheck size={18} strokeWidth={2} />
          <span>Your email & phone stay hidden until you approve a request.</span>
        </div>
        <span className="sr-only">This share card is powered by {personaLabel}.</span>
      </section>
    </div>
  );
}

function PublicAvatar({
  src,
  name,
  agentId,
  small = false,
}: {
  src?: string | null;
  name?: string | null;
  agentId?: string;
  small?: boolean;
}) {
  const [errored, setErrored] = useState(false);
  const normalized = useMemo(() => normalizeAvatar(src), [src]);
  const showImg = !!normalized && !errored;
  const hue = useMemo(() => hashHue(agentId || name || ""), [agentId, name]);

  return (
    <span
      className={`public-avatar ${small ? "public-avatar-small" : ""}`}
      style={{
        background: showImg
          ? "#fffaf0"
          : `linear-gradient(135deg, hsl(${hue} 55% 72%), hsl(${(hue + 34) % 360} 58% 56%))`,
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
        <span>{initials(name)}</span>
      )}
    </span>
  );
}

function PublicShell({ children }: { children: React.ReactNode }) {
  return <div className="public-card-shell">{children}</div>;
}

function normalizeAvatar(url: string | null | undefined): string | null {
  if (!url) return null;
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

function initials(name?: string | null) {
  const parts = (name || "You").trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  return (parts[0]?.slice(0, 2) || "Y").toUpperCase();
}

function slugifyHandle(value: string) {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32) || "you";
}

function buildSubline(persona: PublicPersona) {
  const role = [persona.title, persona.organization].filter(Boolean).join(" at ");
  return [role, persona.location].filter(Boolean).join(" - ");
}

function cardTitle(state: LoadState): string {
  if (state.kind === "ok") return `${state.persona.name} - Persona`;
  return "Persona card";
}
