"use client";

import { useCallback, useEffect, useState } from "react";
import { Calendar, Send, Mail } from "lucide-react";

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
import { Banner, Button, Input, FieldLabel, Tag } from "@/components/ui";
import { getSupabase } from "@/lib/supabase";
import { useDashboard } from "@/contexts/DashboardContext";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
// Bot swapped 2026-05-20: was @zynd_persona_telegram_bot — now @zynd_brief_bot.
const TELEGRAM_BOT = "zynd_brief_bot";

type ConnId = "linkedin" | "calendar" | "email" | "telegram";

interface LinkedinPreview {
  headline?: string;
  currentTitle?: string;
  currentCompany?: string;
  skillsCount?: number;
  postsCount?: number;
  profileUrl?: string;
}

interface ConnState {
  linkedin: { read: boolean; write: boolean; lastReadIso?: string } & LinkedinPreview;
  calendar: { connected: boolean };
  email: { connected: boolean };
  telegram: { connected: boolean };
}

const EMPTY: ConnState = {
  linkedin: { read: false, write: false },
  calendar: { connected: false },
  email: { connected: false },
  telegram: { connected: false },
};

const LINKEDIN_REAL_DATA_KEYS = ["headline", "experience", "education", "skills", "summary"] as const;

function hasRealLinkedinData(rawProfile: Record<string, unknown>): boolean {
  return LINKEDIN_REAL_DATA_KEYS.some((k) => rawProfile[k]);
}

/** Google features share one token; disconnecting one drops all of them. */
function googleSiblingsNote(conn: ConnState, self: "calendar" | "email"): string {
  const label: Record<"calendar" | "email", string> = {
    calendar: "calendar",
    email: "email access",
  };
  const others = (["calendar", "email"] as const)
    .filter((k) => k !== self && conn[k].connected)
    .map((k) => label[k]);
  if (!others.length) return "";
  return `This will also disconnect your ${others.join(" and ")} — they share the same Google account.`;
}

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
  // True while a background LinkedIn scrape is believed to be in flight —
  // covers the gap (up to a few minutes: search-by-name + profile + posts
  // actors on Apify) between "clicked connect/refresh" and the row actually
  // updating. Without this the card just sat there looking unchanged, which
  // read as "nothing happened."
  const [linkedinScraping, setLinkedinScraping] = useState(false);
  const [linkedinNotice, setLinkedinNotice] = useState<string | null>(null);
  // LinkedIn OAuth only gives us the user's name (no profile URL — that
  // needs LinkedIn partner-tier API access we don't have), so the read
  // path falls back to a name search that can land on the wrong person
  // for a common name. Letting the user paste their real URL is the only
  // way to guarantee we're scraping them, not a stranger who shares their
  // name — this is a correction path, reachable whether or not they're
  // already "connected".
  const [linkedinUrlInput, setLinkedinUrlInput] = useState("");

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
    let linkedinPreview: LinkedinPreview = {};
    if (linkedinRes.ok) {
      const data = await linkedinRes.json();
      // `present` alone isn't enough — a just-connected or failed-scrape
      // row exists with no real content, and once `connected` is true the
      // card only offers "Disconnect" (no retry button). Gating on actual
      // profile fields keeps the connect/retry button visible until there's
      // real data, so a failed background scrape can be retried in place
      // instead of requiring a full disconnect + reconnect.
      const rawProfile = data.raw_profile || {};
      if (data.present && hasRealLinkedinData(rawProfile)) {
        linkedinRead = true;
        linkedinLastReadIso = data.scraped_at;
        const topExperience = (rawProfile.experience || [])[0] || {};
        linkedinPreview = {
          headline: rawProfile.headline || undefined,
          currentTitle: topExperience.title || undefined,
          currentCompany: topExperience.companyName || topExperience.company || undefined,
          skillsCount: Array.isArray(rawProfile.skills) ? rawProfile.skills.length : undefined,
          postsCount: Array.isArray(data.raw_posts) ? data.raw_posts.length : undefined,
          profileUrl: data.profile_url || undefined,
        };
      }
    }

    const scopes = google.scopes || "";
    setConn({
      linkedin: {
        read: linkedinRead,
        write: linkedinOauth,
        lastReadIso: linkedinLastReadIso,
        ...linkedinPreview,
      },
      calendar: { connected: google.connected && scopes.includes("calendar") },
      email: { connected: google.connected && scopes.includes("gmail") },
      telegram,
    });
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Polls /api/linkedin/me until the scrape that was just kicked off
  // actually lands (real profile fields + a scraped_at newer than
  // `sinceIso`), or gives up after ~3 minutes. That's the realistic upper
  // bound for the search-by-name + profile + posts Apify actors combined.
  // Without this, clicking connect/refresh looked like a no-op for however
  // long the scrape actually took.
  const pollLinkedinUntilReady = useCallback(
    async (sinceIso: string | undefined) => {
      setLinkedinScraping(true);
      setLinkedinNotice(null);
      const sb = getSupabase();
      const { data: { session } } = await sb.auth.getSession();
      const jwt = session?.access_token;
      if (!jwt) {
        setLinkedinScraping(false);
        return;
      }
      const attempts = 22; // ~3 minutes at 8s apart
      for (let i = 0; i < attempts; i++) {
        await new Promise((r) => setTimeout(r, 8000));
        try {
          const res = await fetch(`${API}/api/linkedin/me`, {
            headers: { Authorization: `Bearer ${jwt}` },
          });
          if (res.ok) {
            const data = await res.json();
            const rawProfile = data.raw_profile || {};
            const ready =
              data.present &&
              hasRealLinkedinData(rawProfile) &&
              data.scraped_at &&
              data.scraped_at !== sinceIso;
            if (ready) {
              await refresh();
              setLinkedinScraping(false);
              return;
            }
          }
        } catch {
          // transient — keep polling
        }
      }
      setLinkedinScraping(false);
      setLinkedinNotice(
        "Still working — this can occasionally take longer than a few minutes. It'll show up here once it lands, no need to reconnect.",
      );
      await refresh();
    },
    [refresh],
  );

  // OAuth callback flash — strip ?oauth=... and refresh state.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const provider = params.get("oauth");
    const status = params.get("status");
    if (provider && status) {
      const detail = params.get("detail");
      const reason = detail && detail !== "already-granted"
        ? detail.length > 200 ? `${detail.slice(0, 200)}…` : detail
        : "";
      setOauthFlash(
        status === "success"
          ? { tone: "success", msg: `${provider} connected.` }
          : {
              tone: "danger",
              msg: reason
                ? `${provider} didn't connect: ${reason}`
                : `${provider} didn't go through. Try again?`,
            },
      );
      window.history.replaceState(null, "", "/dashboard/settings/accounts");
      void refresh();
      if (provider === "linkedin" && status === "success") {
        (async () => {
          const sb = getSupabase();
          const { data: { session } } = await sb.auth.getSession();
          if (session?.access_token) {
            fetch(`${API}/api/linkedin/scrape`, {
              method: "POST",
              headers: { Authorization: `Bearer ${session.access_token}` },
            }).catch(() => {});
            void pollLinkedinUntilReady(undefined);
          }
        })();
      }
      const t = setTimeout(() => setOauthFlash(null), 4000);
      return () => clearTimeout(t);
    }
  }, [refresh, pollLinkedinUntilReady]);

  const buildGoogleConnect = async (features: string): Promise<string | null> => {
    const sb = getSupabase();
    const { data: { session } } = await sb.auth.getSession();
    if (!session?.access_token) return null;
    // Calendar and Email are each their own explicit opt-in. Email is kept
    // separate since sending mail on the user's behalf is a higher-trust
    // action than reading free/busy blocks. The backend unions this request
    // with whatever scopes are already granted, so connecting one feature
    // never revokes another.
    return `${API}/api/oauth/google/authorize?features=${features}&token=${session.access_token}`;
  };

  const connectLinkedIn = async (force = false, profileUrl?: string) => {
    setWorking("linkedin");
    const sinceIso = conn.linkedin.lastReadIso;
    try {
      const sb = getSupabase();
      const { data: { session } } = await sb.auth.getSession();
      if (!session?.access_token) return;
      const params = new URLSearchParams();
      if (force) params.set("force", "1");
      if (profileUrl) params.set("profile_url", profileUrl);
      const qs = params.toString();
      const resp = await fetch(`${API}/api/linkedin/scrape${qs ? `?${qs}` : ""}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        setLinkedinNotice(
          (body?.detail as string) || "Couldn't start the scrape — try again in a moment.",
        );
        return;
      }
      void pollLinkedinUntilReady(sinceIso);
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
        await Promise.all([
          fetch(`${API}/api/linkedin/me`, {
            method: "DELETE",
            headers: { Authorization: `Bearer ${jwt}` },
          }),
          fetch(`${API}/api/connections/linkedin`, {
            method: "DELETE",
            headers: { Authorization: `Bearer ${jwt}` },
          }),
        ]);
      } else if (which === "telegram") {
        await fetch(`${API}/api/connections/telegram`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${jwt}` },
        });
      } else if (which === "calendar" || which === "email") {
        // Calendar and Email share the underlying Google token. Dropping
        // either drops both granted ones — we tell the user that in the
        // inline confirm (see googleSiblingsNote).
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
      if (!conn.linkedin.read && !conn.linkedin.write) {
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
    const url = await buildGoogleConnect(id === "email" ? "gmail" : "calendar");
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
        <h1 className="display-s">Connections</h1>
        <p className="body secondary">Four things your Persona can see. Nothing else.</p>
      </div>

      <div className="connectors-grid">
        <ConnectorCard
          id="linkedin"
          icon={<LinkedinIcon size={22} />}
          name="LinkedIn"
          connected={conn.linkedin.read}
          pending={linkedinScraping}
          pendingLabel="Reading…"
          loading={loading}
          working={working === "linkedin"}
          confirming={confirming === "linkedin"}
          description={
            conn.linkedin.write
              ? "Your Persona reads your posts and profile. It also has permission to post on your behalf. Data isn't refreshed automatically — use Refresh below to pull the latest."
              : "Your Persona reads your posts and profile. Data isn't refreshed automatically — use Refresh below to pull the latest."
          }
          meta={
            linkedinScraping
              ? "Fetching your profile from LinkedIn — this usually takes 1–2 minutes."
              : conn.linkedin.read
                ? `${conn.linkedin.write ? "Read + Post" : "Read only"} · Last read ${timeAgo(conn.linkedin.lastReadIso) || "recently"}`
                : linkedinNotice || undefined
          }
          extra={
            conn.linkedin.read ? (
              <div className="what-we-read">
                <div><strong>What Persona read:</strong> {conn.linkedin.headline || "(no headline set)"}</div>
                {(conn.linkedin.currentTitle || conn.linkedin.currentCompany) && (
                  <div>
                    Current: {conn.linkedin.currentTitle || "—"}
                    {conn.linkedin.currentCompany ? ` @ ${conn.linkedin.currentCompany}` : ""}
                  </div>
                )}
                <div>
                  {conn.linkedin.skillsCount ?? 0} skill{conn.linkedin.skillsCount === 1 ? "" : "s"} ·{" "}
                  {conn.linkedin.postsCount ?? 0} recent post{conn.linkedin.postsCount === 1 ? "" : "s"}
                </div>
                {conn.linkedin.profileUrl && (
                  <div>
                    <a href={conn.linkedin.profileUrl} target="_blank" rel="noreferrer">
                      View the profile we scraped ↗
                    </a>
                  </div>
                )}
              </div>
            ) : undefined
          }
          connectLabel={
            conn.linkedin.read && !conn.linkedin.write
              ? "Allow my Persona to post"
              : "Let my Persona read my LinkedIn"
          }
          permission={conn.linkedin.write ? "Can post" : undefined}
          confirmNote={
            conn.linkedin.write
              ? "This removes your scraped profile data and any posting permission you granted."
              : "This removes your scraped profile data."
          }
          onConnect={() => handleConnect("linkedin")}
          onAskDisconnect={() => setConfirming("linkedin")}
          onCancelConfirm={() => setConfirming(null)}
          onConfirmDisconnect={() => disconnect("linkedin")}
          secondaryActions={
            conn.linkedin.read && !confirming
              ? [
                  { label: "Refresh now", onClick: () => void connectLinkedIn(true), disabled: linkedinScraping },
                  ...(!conn.linkedin.write
                    ? [{ label: "Allow posting", onClick: () => oauthLinkedIn() }]
                    : []),
                ]
              : []
          }
          footer={
            <div className="linkedin-url-footer">
              <FieldLabel htmlFor="linkedin-profile-url-input">LinkedIn profile URL</FieldLabel>
              <p className="field-hint">
                {conn.linkedin.read
                  ? "Wrong profile above? Paste your exact URL to fix it."
                  : "Know your URL? Paste it for a guaranteed-correct match — LinkedIn's login alone can't tell us which \"you\" you are among people with the same name."}
              </p>
              <div className="linkedin-url-row">
                <Input
                  id="linkedin-profile-url-input"
                  type="text"
                  placeholder="https://www.linkedin.com/in/your-name"
                  value={linkedinUrlInput}
                  onChange={(e) => setLinkedinUrlInput(e.target.value)}
                  disabled={working === "linkedin" || linkedinScraping}
                />
                <Button
                  size="sm"
                  variant="tertiary"
                  disabled={!linkedinUrlInput.trim() || working === "linkedin" || linkedinScraping}
                  onClick={() => {
                    const url = linkedinUrlInput.trim();
                    if (!url) return;
                    void connectLinkedIn(true, url);
                    setLinkedinUrlInput("");
                  }}
                >
                  Use this URL
                </Button>
              </div>
            </div>
          }
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
          confirmNote={googleSiblingsNote(conn, "calendar")}
          onConnect={() => handleConnect("calendar")}
          onAskDisconnect={() => setConfirming("calendar")}
          onCancelConfirm={() => setConfirming(null)}
          onConfirmDisconnect={() => disconnect("calendar")}
        />

        <ConnectorCard
          id="email"
          icon={<Mail size={22} strokeWidth={1.5} />}
          name="Email"
          connected={conn.email.connected}
          loading={loading}
          working={working === "email"}
          confirming={confirming === "email"}
          description="Your Persona can search your inbox and send emails on your behalf when you ask it to in chat."
          meta={conn.email.connected ? "Read + send via Gmail" : undefined}
          connectLabel="Let my Persona send email for me"
          permission={conn.email.connected ? "Can send" : undefined}
          confirmNote={googleSiblingsNote(conn, "email")}
          onConnect={() => handleConnect("email")}
          onAskDisconnect={() => setConfirming("email")}
          onCancelConfirm={() => setConfirming(null)}
          onConfirmDisconnect={() => disconnect("email")}
        />

        <ConnectorCard
          id="telegram"
          icon={<Send size={22} strokeWidth={1.5} />}
          name="Telegram"
          connected={conn.telegram.connected}
          loading={loading}
          working={working === "telegram"}
          confirming={confirming === "telegram"}
          description="Your Persona can text with you on Telegram. Message it from your phone; replies sync back here."
          connectLabel="Let my Persona text me on Telegram"
          confirmNote="Your Persona will stop replying to messages on Telegram."
          onConnect={() => handleConnect("telegram")}
          onAskDisconnect={() => setConfirming("telegram")}
          onCancelConfirm={() => setConfirming(null)}
          onConfirmDisconnect={() => disconnect("telegram")}
        />
      </div>
    </div>
  );
}

interface SecondaryAction {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}

interface ConnectorCardProps {
  id: ConnId;
  icon: React.ReactNode;
  name: string;
  connected: boolean;
  /** True while a connected-but-not-yet-ready background job (e.g. a
   *  LinkedIn scrape) is in flight. Shows a distinct amber status instead
   *  of flatly "Not connected", which otherwise reads as a failure. */
  pending?: boolean;
  pendingLabel?: string;
  loading: boolean;
  working: boolean;
  confirming: boolean;
  description: string;
  meta?: string;
  /** Short badge next to the status pill for connections that can act on
   *  the user's behalf (post, send), not just read — e.g. "Can post",
   *  "Can send". Omit for read-only connections. */
  permission?: string;
  /** Extra content (e.g. a "what we actually read" preview) rendered
   *  between the meta line and the action buttons. Only shown when
   *  `connected`. */
  extra?: React.ReactNode;
  connectLabel: string;
  /** Note shown above the Confirm button when disconnect would have side-effects. */
  confirmNote: string;
  onConnect: () => void;
  onAskDisconnect: () => void;
  onCancelConfirm: () => void;
  onConfirmDisconnect: () => void;
  /** Extra buttons shown next to Disconnect once connected — e.g. a manual
   *  "Refresh now". Without these, a connected card offered no action
   *  except disconnecting, so a stuck or stale connection had no in-place
   *  fix short of a full disconnect + reconnect. */
  secondaryActions?: SecondaryAction[];
  /** Rendered at the very bottom of the card, in every state (connected,
   *  pending, not connected) — unlike `extra`, which only shows once
   *  connected. Used for things that need to work regardless of state,
   *  e.g. LinkedIn's "paste your profile URL" correction, which has to be
   *  reachable both before first connecting and after a wrong auto-match. */
  footer?: React.ReactNode;
}

function ConnectorCard({
  icon,
  name,
  connected,
  pending,
  pendingLabel,
  loading,
  working,
  confirming,
  description,
  meta,
  permission,
  extra,
  connectLabel,
  confirmNote,
  onConnect,
  onAskDisconnect,
  onCancelConfirm,
  onConfirmDisconnect,
  secondaryActions,
  footer,
}: ConnectorCardProps) {
  const statusText = loading
    ? "…"
    : pending
      ? pendingLabel || "Working…"
      : connected
        ? "Connected"
        : "Not connected";
  return (
    <div
      className={`connector-card ${
        loading ? "loading" : pending ? "pending" : connected ? "" : "disconnected"
      }`}
    >
      <div className="top-row">
        <span className="ico">{icon}</span>
        <span className="name">{name}</span>
        {permission && connected && <Tag>{permission}</Tag>}
        <span className="status">{statusText}</span>
      </div>
      <p className="description">{description}</p>
      {confirming && confirmNote && (
        <p className="confirm-note">{confirmNote}</p>
      )}
      {connected && extra}
      <div className="bottom-row">
        {meta && !confirming && <span className="meta">{meta}</span>}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
          {connected ? (
            confirming ? (
              <>
                <Button size="sm" variant="tertiary" onClick={onCancelConfirm}>Cancel</Button>
                <Button size="sm" variant="destructive" onClick={onConfirmDisconnect} disabled={working}>
                  {working ? "…" : "Disconnect"}
                </Button>
              </>
            ) : (
              <>
                {secondaryActions?.map((action) => (
                  <Button
                    key={action.label}
                    size="sm"
                    variant="tertiary"
                    onClick={action.onClick}
                    disabled={action.disabled ?? working}
                  >
                    {action.label}
                  </Button>
                ))}
                <Button size="sm" variant="tertiary" onClick={onAskDisconnect}>
                  Disconnect
                </Button>
              </>
            )
          ) : (
            <Button size="sm" onClick={onConnect} disabled={working}>
              {working ? "Opening…" : connectLabel}
            </Button>
          )}
        </div>
      </div>
      {!confirming && footer}
    </div>
  );
}
