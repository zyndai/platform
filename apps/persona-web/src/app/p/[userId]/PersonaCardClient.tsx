"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
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
import { QrCode as QrCodeImage } from "@/components/QrCode";
import { getSupabase } from "@/lib/supabase";
import type { PublicPersona } from "./utils";
import { normalizeAvatar, hashHue, initials } from "./utils";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface PersonaCardClientProps {
  persona: PublicPersona;
  userId: string;
}

export function PersonaCardClient({ persona, userId }: PersonaCardClientProps) {
  const router = useRouter();

  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);

  const firstName = persona.name?.split(" ")[0] || "this agent";
  const personaLabel = `${firstName}'s persona`;
  const subline = [persona.title, persona.organization].filter(Boolean).join(" · ");
  const bio = persona.description?.trim() || "";
  const showBooking = persona.visibility?.calendar !== false;

  const publicHref = typeof window !== "undefined" && userId
    ? new URL(`/p/${userId}`, window.location.origin).toString()
    : "";

  const publicUrl = typeof window !== "undefined" && userId
    ? `${window.location.host}/p/${String(userId).slice(0, 8)}`
    : "your card";

  const handleConnect = useCallback(async () => {
    const sb = getSupabase();
    const { data: { session } } = await sb.auth.getSession();
    const myUserId = session?.user?.id;
    if (!myUserId) {
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
          target_agent_id: persona.agent_id,
          target_name: persona.name || "Network Agent",
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
  }, [persona, userId, router]);

  const handleCopy = useCallback(async () => {
    const url = publicHref;
    if (!url) return;
    await navigator.clipboard.writeText(url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }, [publicHref]);

  const handleNativeShare = useCallback(async () => {
    const url = publicHref;
    if (!url) return;
    try {
      if (navigator.share) {
        await navigator.share({ url, title: `${persona.name} - Persona` });
        return;
      }
      await handleCopy();
    } catch {
      /* user cancelled */
    }
  }, [handleCopy, publicHref, persona.name]);

  return (
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
            <span>{showBooking ? "Ask about my work - book time" : "Ask about my work"}</span>
          </div>
          <button
            type="button"
            onClick={handleConnect}
            disabled={connecting}
            aria-label={`Message ${firstName}`}
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
          {showBooking && (
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
          )}
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
    </main>
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
