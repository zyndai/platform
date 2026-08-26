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

function XIcon({ size = 22 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  );
}

function GithubIcon({ size = 22 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
    </svg>
  );
}
import { Banner, Button, Input, FieldLabel, Tag } from "@/components/ui";
import { getSupabase } from "@/lib/supabase";
import { useDashboard } from "@/contexts/DashboardContext";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
// Bot swapped 2026-05-20: was @zynd_persona_telegram_bot — now @zynd_brief_bot.
const TELEGRAM_BOT = "zynd_brief_bot";

type ConnId = "linkedin" | "calendar" | "email" | "telegram" | "twitter" | "github";

interface LinkedinPreview {
  headline?: string;
  currentTitle?: string;
  currentCompany?: string;
  skillsCount?: number;
  postsCount?: number;
  profileUrl?: string;
}

/** OAuth-only platforms: connected via a plain OAuth handshake that
 *  captures the username (no scrape, no read/write permissions). */
interface SocialConn {
  connected: boolean;
  username?: string;
}

interface ConnState {
  linkedin: { read: boolean; write: boolean; lastReadIso?: string } & LinkedinPreview;
  calendar: { connected: boolean };
  email: { connected: boolean };
  telegram: { connected: boolean };
  /** Twitter is username-based, not OAuth: the handle is stored in the
   *  persona profile (profile.twitter), same place the "You" page edits it. */
  twitter: { username: string };
  github: SocialConn;
}

const EMPTY: ConnState = {
  linkedin: { read: false, write: false },
  calendar: { connected: false },
  email: { connected: false },
  telegram: { connected: false },
  twitter: { username: "" },
  github: { connected: false },
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

/** Accepts "@handle", "handle", or a profile URL like
 *  https://x.com/handle — returns the bare handle. */
function normalizeTwitterHandle(raw: string): string {
  let v = raw.trim().replace(/^@/, "");
  if (/^https?:\/\//i.test(v)) {
    try {
      v = new URL(v).pathname.split("/").filter(Boolean).pop() ?? v;
    } catch {
      // not a parseable URL — keep the raw value as-is
    }
  }
  return v.replace(/[/\s]+$/, "");
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
  // covers the gap (up to a few minutes: profile + posts actors on Apify)
  // between "clicked connect/refresh" and the row actually updating.
  // Without this the card just sat there looking unchanged, which read
  // as "nothing happened."
  const [linkedinScraping, setLinkedinScraping] = useState(false);
  const [linkedinNotice, setLinkedinNotice] = useState<string | null>(null);
  // Scraping is strictly opt-in and URL-driven: LinkedIn's OAuth only
  // gives us the user's name (no profile URL — that needs LinkedIn
  // partner-tier API access we don't have), so the user pastes their
  // real URL and we scrape exactly that profile — never a guess at
  // someone else who shares their name. This input is the correction
  // path, reachable whether or not they're already "connected".
  const [linkedinUrlInput, setLinkedinUrlInput] = useState("");
  // Twitter is username-based: the handle lives in the persona profile
  // (profile.twitter), not in an OAuth token. The whole profile blob is
  // kept so saves can merge the twitter key without clobbering anything
  // else the user set (same pattern as the "You" page).
  const [twitterUsernameInput, setTwitterUsernameInput] = useState("");
  const [personaProfile, setPersonaProfile] = useState<Record<string, unknown>>({});

  const refresh = useCallback(async () => {
    const sb = getSupabase();
    const { data: { session } } = await sb.auth.getSession();
    const jwt = session?.access_token;
    if (!jwt) return;

    const [connRes, linkedinRes, personaRes] = await Promise.all([
      fetch(`${API}/api/connections/`, {
        headers: { Authorization: `Bearer ${jwt}` },
      }),
      fetch(`${API}/api/linkedin/me`, {
        headers: { Authorization: `Bearer ${jwt}` },
      }),
      session?.user?.id
        ? fetch(`${API}/api/persona/${session.user.id}/status`)
        : Promise.resolve(null),
    ]);

    let google = { connected: false, scopes: "" };
    let linkedinOauth = false;
    let telegram = { connected: false };
    let github: SocialConn = { connected: false };
    if (connRes.ok) {
      const data = await connRes.json();
      google = data.connections?.google ?? google;
      linkedinOauth = data.connections?.linkedin?.connected ?? false;
      telegram = data.connections?.telegram ?? telegram;
      github = data.connections?.github ?? github;
    }

    let twitterUsername = "";
    if (personaRes && personaRes.ok) {
      const data = await personaRes.json();
      const profile = (data?.profile || {}) as Record<string, unknown>;
      setPersonaProfile(profile);
      twitterUsername = String(profile.twitter || "");
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
      twitter: { username: twitterUsername },
      github,
    });
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Polls /api/linkedin/me until the scrape that was just kicked off
  // actually lands (real profile fields + a scraped_at newer than
  // `sinceIso`), or gives up after ~3 minutes. That's the realistic upper
  // bound for the profile + posts Apify actors combined. Without this,
  // clicking connect/refresh looked like a no-op for however long the
  // scrape actually took.
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
          if (!session?.access_token) return;
          // Scraping requires a profile URL (name guessing is gone). Only
          // auto-kick the scrape when one is already stored; otherwise
          // point the user at the paste-URL field on this card.
          const liRes = await fetch(`${API}/api/linkedin/me`, {
            headers: { Authorization: `Bearer ${session.access_token}` },
          }).catch(() => null);
          const li = liRes && liRes.ok ? await liRes.json().catch(() => ({})) : {};
          if (li.profile_url) {
            fetch(`${API}/api/linkedin/scrape`, {
              method: "POST",
              headers: { Authorization: `Bearer ${session.access_token}` },
            }).catch(() => {});
            void pollLinkedinUntilReady(undefined);
          } else {
            setLinkedinNotice(
              "Connected — paste your LinkedIn profile URL below so Persona can read your profile. LinkedIn's login alone doesn't tell us which profile is yours.",
            );
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

  // Twitter has no OAuth — the handle is saved straight into the persona
  // profile (profile.twitter), merged with the rest of the profile blob so
  // nothing else the user set gets clobbered.
  const saveTwitterUsername = async () => {
    const handle = normalizeTwitterHandle(twitterUsernameInput);
    if (!user || !handle) return;
    setWorking("twitter");
    try {
      const res = await fetch(`${API}/api/persona/${user.id}/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile: { ...personaProfile, twitter: handle } }),
      });
      if (res.ok) {
        setTwitterUsernameInput("");
        await refresh();
      }
    } finally {
      setWorking(null);
    }
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
      } else if (which === "twitter") {
        await fetch(`${API}/api/persona/${session.user.id}/profile`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profile: { ...personaProfile, twitter: "" } }),
        });
      } else if (which === "github") {
        await fetch(`${API}/api/connections/${which}`, {
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
      if (conn.linkedin.write && !conn.linkedin.read) {
        // OAuth is connected but no profile was ever scraped — scraping
        // is URL-driven now, so point the user at the paste field instead
        // of firing a scrape that would just skip.
        setLinkedinNotice("Paste your LinkedIn profile URL below so Persona can read your profile.");
        document.getElementById("linkedin-profile-url-input")?.focus();
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
    if (id === "twitter") {
      // No OAuth for Twitter — jump the user to the username input.
      document.getElementById("twitter-username-input")?.focus();
      return;
    }
    if (id === "github") {
      // OAuth-only connect: redirect to the backend authorize endpoint,
      // which bounces to the provider and back to this page with a flash.
      setWorking(id);
      const sb = getSupabase();
      const { data: { session } } = await sb.auth.getSession();
      if (!session?.access_token) {
        setWorking(null);
        return;
      }
      window.location.href = `${API}/api/oauth/${id}/authorize?token=${session.access_token}`;
      return;
    }
    const url = await buildGoogleConnect(id === "email" ? "gmail" : "calendar");
    if (url) window.location.href = url;
  };

  // One array of cards so the page can split them into a "Connected"
  // section and a "Not connected" section. A card belongs to the
  // connected group while it has a live connection — LinkedIn also
  // counts while a background scrape is in flight, since it's
  // connected-but-not-yet-ready rather than flatly disconnected.
  const connectorCards = [
    {
      connected: conn.linkedin.read || linkedinScraping,
      card: (
<ConnectorCard
          key="linkedin"
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
                  : "Paste your profile URL and hit \u201cUse this URL\u201d — that's how Persona reads your profile. LinkedIn's login alone doesn't tell us which profile is yours."}
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
      ),
    },
    {
      connected: conn.calendar.connected,
      card: (
        <ConnectorCard
          key="calendar"
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
      ),
    },
    {
      connected: conn.email.connected,
      card: (
        <ConnectorCard
          key="email"
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
      ),
    },
    {
      connected: conn.telegram.connected,
      card: (
        <ConnectorCard
          key="telegram"
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
      ),
    },
    {
      connected: !!conn.twitter.username,
      card: (
        <ConnectorCard
          key="twitter"
          id="twitter"
          icon={<XIcon size={22} />}
          name="X (Twitter)"
          connected={!!conn.twitter.username}
          loading={loading}
          working={working === "twitter"}
          confirming={confirming === "twitter"}
          description="Your Persona reads your X profile to learn what you're into. We only read your public profile — nothing gets posted on your behalf."
          meta={
            conn.twitter.username
              ? `Connected as @${conn.twitter.username}`
              : undefined
          }
          connectLabel="Add my username"
          confirmNote="This clears your saved username."
          onConnect={() => handleConnect("twitter")}
          onAskDisconnect={() => setConfirming("twitter")}
          onCancelConfirm={() => setConfirming(null)}
          onConfirmDisconnect={() => disconnect("twitter")}
          footer={
            <div className="linkedin-url-footer">
              <FieldLabel htmlFor="twitter-username-input">Twitter / X username</FieldLabel>
              <p className="field-hint">
                {conn.twitter.username
                  ? "Wrong handle above? Paste your exact handle to fix it."
                  : "Know your handle? Paste it — we'll read your public X profile from there."}
              </p>
              <div className="linkedin-url-row">
                <Input
                  id="twitter-username-input"
                  type="text"
                  placeholder="@handle or https://x.com/handle"
                  value={twitterUsernameInput}
                  onChange={(e) => setTwitterUsernameInput(e.target.value)}
                  disabled={working === "twitter"}
                />
                <Button
                  size="sm"
                  variant="tertiary"
                  disabled={!twitterUsernameInput.trim() || working === "twitter"}
                  onClick={() => void saveTwitterUsername()}
                >
                  Use this handle
                </Button>
              </div>
            </div>
          }
        />
      ),
    },
    {
      connected: conn.github.connected,
      card: (
        <ConnectorCard
          key="github"
          id="github"
          icon={<GithubIcon size={22} />}
          name="GitHub"
          connected={conn.github.connected}
          loading={loading}
          working={working === "github"}
          confirming={confirming === "github"}
          description="Your Persona connects to your GitHub profile to learn what you build. Read-only — we never touch your repos."
          meta={
            conn.github.connected
              ? conn.github.username
                ? `Connected as @${conn.github.username}`
                : "Connected"
              : undefined
          }
          connectLabel="Connect my GitHub"
          confirmNote="Your Persona will lose access to your GitHub profile."
          onConnect={() => handleConnect("github")}
          onAskDisconnect={() => setConfirming("github")}
          onCancelConfirm={() => setConfirming(null)}
          onConfirmDisconnect={() => disconnect("github")}
        />
      ),
    },
  ];
  const connectedCards = connectorCards.filter((c) => c.connected);
  const notConnectedCards = connectorCards.filter((c) => !c.connected);

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
        <p className="body secondary">Six things your Persona can see. Nothing else.</p>
      </div>

      {/* While loading (or before anything is connected) every card reads
          as "Not connected", so keep a single ungrouped grid to avoid a
          flash of mis-grouped cards. Once at least one connection exists,
          split into a Connected section and a Not connected section. */}
      {connectedCards.length === 0 ? (
        <div className="connectors-grid">
          {connectorCards.map((c) => c.card)}
        </div>
      ) : (
        <>
          <section className="connections-section">
            <h2>Connected</h2>
            <div className="connectors-grid">
              {connectedCards.map((c) => c.card)}
            </div>
          </section>
          {notConnectedCards.length > 0 && (
            <section className="connections-section">
              <h2>Not connected</h2>
              <div className="connectors-grid">
                {notConnectedCards.map((c) => c.card)}
              </div>
            </section>
          )}
        </>
      )}
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
