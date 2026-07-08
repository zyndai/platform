"use client";

import { useCallback, useEffect, useState } from "react";
import { FileText, Calendar, Send } from "lucide-react";

// Lucide dropped brand glyphs in v0.452 (trademark concerns), so the
// LinkedIn mark is inlined here. Sized + stroked to match other icons.
function LinkedinIcon({ size = 22 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M20.45 20.45h-3.55v-5.57c0-1.33-.03-3.04-1.85-3.04-1.86 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zm1.78 13.02H3.55V9h3.57v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z" />
    </svg>
  );
}
import { Banner, Button } from "@/components/ui";
import { getSupabase } from "@/lib/supabase";
import { useDashboard } from "@/contexts/DashboardContext";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
// Bot swapped 2026-05-20: was @zynd_persona_telegram_bot — now @zynd_brief_bot.
const TELEGRAM_BOT = "zynd_brief_bot";

type ConnId = "linkedin" | "brief" | "calendar" | "telegram";

interface ConnState {
  linkedin: { read: boolean; write: boolean; lastReadIso?: string };
  brief: { connected: boolean };
  calendar: { connected: boolean };
  telegram: { connected: boolean };
}

const EMPTY: ConnState = {
  linkedin: { read: false, write: false },
  brief: { connected: false },
  calendar: { connected: false },
  telegram: { connected: false },
};

function timeAgo(iso: string | undefined): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 0) return "just now";
  const m = Math.floor(ms / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} minute${m === 1 ? "" : "s"} ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.floor(h / 24);
  return `${d} day${d === 1 ? "" : "s"} ago`;
}

export default function AccountsPage() {
  const { user } = useDashboard();
  const [conn, setConn] = useState<ConnState>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<ConnId | null>(null);
  const [confirming, setConfirming] = useState<ConnId | null>(null);
  const [oauthFlash, setOauthFlash] =
    useState<{ tone: "success" | "danger"; msg: string } | null>(null);

  const refresh = useCallback(async () => {
    const sb = getSupabase();
    const { data: { session } } = await sb.auth.getSession();
    const jwt = session?.access_token;
    if (!jwt) return;

    const [connRes, linkedinRes] = await Promise.all([
      fetch(`${API}/api/connections/`, {
        headers: { Authorization: `Bearer ${jwt}` },
      }),
      fetch(`${API}/api/linkedin/me`, {
        headers: { Authorization: `Bearer ${jwt}` },
      }),
    ]);

    let google = { connected: false, scopes: "" };
    let linkedinOauth = false;
    let telegram = { connected: false };
    if (connRes.ok) {
      const data = await connRes.json();
      google = data.connections?.google ?? google;
      linkedinOauth = data.connections?.linkedin?.connected ?? false;
      telegram = data.connections?.telegram ?? telegram;
    }

    let linkedinRead = false;
    let linkedinLastReadIso: string | undefined;
    if (linkedinRes.ok) {
      const data = await linkedinRes.json();
      if (data.present) {
        linkedinRead = true;
        linkedinLastReadIso = data.scraped_at;
      }
    }

    const scopes = google.scopes || "";
    setConn({
      linkedin: { read: linkedinRead, write: linkedinOauth, lastReadIso: linkedinLastReadIso },
      brief: { connected: google.connected && (scopes.includes("documents") || scopes.includes("drive")) },
      calendar: { connected: google.connected && scopes.includes("calendar") },
      telegram,
    });
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // OAuth callback flash — strip ?oauth=... and refresh state.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const provider = params.get("oauth");
    const status = params.get("status");
    if (provider && status) {
      setOauthFlash(
        status === "success"
          ? { tone: "success", msg: `${provider} connected.` }
          : { tone: "danger",  msg: `${provider} didn't go through. Try again?` },
      );
      window.history.replaceState(null, "", "/dashboard/settings/accounts");
      void refresh();
      const t = setTimeout(() => setOauthFlash(null), 4000);
      return () => clearTimeout(t);
    }
  }, [refresh]);

  const buildGoogleConnect = async (): Promise<string | null> => {
    const sb = getSupabase();
    const { data: { session } } = await sb.auth.getSession();
    if (!session?.access_token) return null;
    // Always request both Docs + Calendar so the user goes through Google's
    // consent screen exactly once. Whichever card was clicked, the other
    // capability is granted alongside — and a follow-up click won't show
    // a redundant consent (oauth_routes skips re-consent when the scope set
    // is already covered).
    return `${API}/api/oauth/google/authorize?features=docs,calendar&token=${session.access_token}`;
  };

  const connectLinkedIn = async () => {
    setWorking("linkedin");
    try {
      const sb = getSupabase();
      const { data: { session } } = await sb.auth.getSession();
      if (!session?.access_token) return;
      await fetch(`${API}/api/linkedin/scrape`, {
        method: "POST",
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      setTimeout(() => void refresh(), 1500);
    } finally {
      setWorking(null);
    }
  };

  const oauthLinkedIn = () => {
    setWorking("linkedin");
    const sb = getSupabase();
    sb.auth.getSession().then(({ data: { session } }) => {
      if (!session?.access_token) return;
      window.location.href = `${API}/api/oauth/linkedin/authorize?token=${session.access_token}`;
    }).catch(() => setWorking(null));
  };

  const disconnect = async (which: ConnId) => {
    setWorking(which);
    try {
      const sb = getSupabase();
      const { data: { session } } = await sb.auth.getSession();
      const jwt = session?.access_token;
      if (!jwt) return;

      if (which === "linkedin") {
        await fetch(`${API}/api/linkedin/me`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${jwt}` },
        });
        await fetch(`${API}/api/connections/linkedin`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${jwt}` },
        });
      } else if (which === "telegram") {
        await fetch(`${API}/api/connections/telegram`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${jwt}` },
        });
      } else if (which === "brief" || which === "calendar") {
        // Brief and Calendar share the underlying Google token. Dropping
        // either drops both — we tell the user that in the inline confirm.
        await fetch(`${API}/api/connections/google`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${jwt}` },
        });
      }
      setConfirming(null);
      await refresh();
    } finally {
      setWorking(null);
    }
  };

  const handleConnect = async (id: ConnId) => {
    if (id === "linkedin") {
      if (conn.linkedin.read && !conn.linkedin.write) {
        oauthLinkedIn();
        return;
      }
      await connectLinkedIn();
      return;
    }
    if (id === "telegram") {
      if (!user) return;
      window.open(
        `https://t.me/${TELEGRAM_BOT}?start=${user.id}`,
        "_blank",
      );
      return;
    }
    const url = await buildGoogleConnect();
    if (url) window.location.href = url;
  };

  return (
    <div className="settings-main">
      {oauthFlash && (
        <div style={{ marginBottom: 16 }}>
          <Banner
            tone={oauthFlash.tone}
            onDismiss={() => setOauthFlash(null)}
          >
            {oauthFlash.msg}
          </Banner>
        </div>
      )}
      <div className="settings-header">
        <p className="body secondary">Four things your Persona can see. Nothing else.</p>
      </div>

      <div className="connectors-grid">
        <ConnectorCard
          id="linkedin"
          icon={<LinkedinIcon size={22} />}
          name="LinkedIn"
          connected={conn.linkedin.read}
          loading={loading}
          working={working === "linkedin"}
          confirming={confirming === "linkedin"}
          description={
            conn.linkedin.write
              ? "Your Persona reads your posts and profile. It also has permission to post on your behalf."
              : "Your Persona reads your posts and profile every few hours to keep up with what you're into."
          }
          meta={
            conn.linkedin.read
              ? `${conn.linkedin.write ? "Read + Post" : "Read only"} · Last read ${timeAgo(conn.linkedin.lastReadIso) || "recently"}`
              : undefined
          }
          connectLabel={
            conn.linkedin.read && !conn.linkedin.write
              ? "Allow my Persona to post"
              : "Let my Persona read my LinkedIn"
          }
          confirmNote=""
          onConnect={() => handleConnect("linkedin")}
          onAskDisconnect={() => setConfirming("linkedin")}
          onCancelConfirm={() => setConfirming(null)}
          onConfirmDisconnect={() => disconnect("linkedin")}
        />

        <ConnectorCard
          id="brief"
          icon={<FileText size={22} strokeWidth={1.5} />}
          name="Your brief"
          connected={conn.brief.connected}
          loading={loading}
          working={working === "brief"}
          confirming={confirming === "brief"}
          description="A doc in your Drive where you tell your Persona what's current. It re-reads whenever it changes."
          meta={conn.brief.connected ? "Connected to Google Drive" : undefined}
          connectLabel="Create my brief"
          confirmNote={conn.calendar.connected ? "This will also stop your Persona reading your calendar." : ""}
          onConnect={() => handleConnect("brief")}
          onAskDisconnect={() => setConfirming("brief")}
          onCancelConfirm={() => setConfirming(null)}
          onConfirmDisconnect={() => disconnect("brief")}
        />

        <ConnectorCard
          id="calendar"
          icon={<Calendar size={22} strokeWidth={1.5} />}
          name="Calendar"
          connected={conn.calendar.connected}
          loading={loading}
          working={working === "calendar"}
          confirming={confirming === "calendar"}
          description="Your Persona sees your busy and free blocks so it can offer real meeting times. It never sees what your meetings are about."
          meta={conn.calendar.connected ? "Reading your primary calendar" : undefined}
          connectLabel="Let my Persona see when I'm free"
          confirmNote={conn.brief.connected ? "This will also stop your Persona reading your brief." : ""}
          onConnect={() => handleConnect("calendar")}
          onAskDisconnect={() => setConfirming("calendar")}
          onCancelConfirm={() => setConfirming(null)}
          onConfirmDisconnect={() => disconnect("calendar")}
        />

        <ConnectorCard
          id="telegram"
          icon={<Send size={22} strokeWidth={1.5} />}
          name="Telegram"
          connected={conn.telegram.connected}
          loading={loading}
          working={working === "telegram"}
          confirming={confirming === "telegram"}
          description="Text your Persona from your phone. It replies in Telegram; everything syncs back here."
          meta={conn.telegram.connected ? "Connected" : undefined}
          connectLabel="Connect Telegram"
          confirmNote=""
          onConnect={() => handleConnect("telegram")}
          onAskDisconnect={() => setConfirming("telegram")}
          onCancelConfirm={() => setConfirming(null)}
          onConfirmDisconnect={() => disconnect("telegram")}
        />
      </div>
    </div>
  );
}

interface ConnectorCardProps {
  id: ConnId;
  icon: React.ReactNode;
  name: string;
  connected: boolean;
  loading: boolean;
  working: boolean;
  confirming: boolean;
  description: string;
  meta?: string;
  connectLabel: string;
  /** Note shown above the Confirm button when disconnect would have side-effects. */
  confirmNote: string;
  onConnect: () => void;
  onAskDisconnect: () => void;
  onCancelConfirm: () => void;
  onConfirmDisconnect: () => void;
}

function ConnectorCard({
  icon,
  name,
  connected,
  loading,
  working,
  confirming,
  description,
  meta,
  connectLabel,
  confirmNote,
  onConnect,
  onAskDisconnect,
  onCancelConfirm,
  onConfirmDisconnect,
}: ConnectorCardProps) {
  return (
    <div className={`connector-card ${connected ? "" : "disconnected"}`}>
      <div className="top-row">
        <span className="ico">{icon}</span>
        <span className="name">{name}</span>
        <span className="status">{loading ? "…" : connected ? "Connected" : "Not connected"}</span>
      </div>
      <p className="description">{description}</p>
      {confirming && confirmNote && (
        <p className="confirm-note caption">{confirmNote}</p>
      )}
      <div className="bottom-row">
        {meta && !confirming && <span className="meta">{meta}</span>}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          {connected ? (
            confirming ? (
              <>
                <Button size="sm" variant="tertiary" onClick={onCancelConfirm}>Cancel</Button>
                <Button size="sm" variant="destructive" onClick={onConfirmDisconnect} disabled={working}>
                  {working ? "…" : "Disconnect"}
                </Button>
              </>
            ) : (
              <Button size="sm" variant="tertiary" onClick={onAskDisconnect}>
                Disconnect
              </Button>
            )
          ) : (
            <Button size="sm" onClick={onConnect} disabled={working}>
              {working ? "Opening…" : connectLabel}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
