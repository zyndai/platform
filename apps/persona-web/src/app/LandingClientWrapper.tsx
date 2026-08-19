"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { X, Plug, MessageSquareText, Waypoints, FileOutput } from "lucide-react";
import { getSupabase } from "@/lib/supabase";
import { captureZyndOAuthReq } from "@/lib/zynd-oauth";
import { Monogram } from "@/components/ui";

type OAuthProvider = "linkedin_oidc";

function LinkedInLogo({ size = 20 }: { size?: number }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24">
      <path fill="#0A66C2" d="M20.45 20.45h-3.55v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.13 1.45-2.13 2.94v5.67H9.36V9h3.41v1.56h.05c.48-.91 1.65-1.85 3.4-1.85 3.64 0 4.31 2.4 4.31 5.51v6.23zM5.34 7.43a2.06 2.06 0 11.01-4.13 2.06 2.06 0 010 4.13zM7.12 20.45H3.56V9h3.56v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.72v20.56C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.72V1.72C24 .77 23.2 0 22.22 0z" />
    </svg>
  );
}

const MCP_CLIENTS = [
  { name: "Claude", logoUrl: "https://anthropic.gallerycdn.vsassets.io/extensions/anthropic/claude-code/2.1.235/1787085642251/Microsoft.VisualStudio.Services.Icons.Default", color: "#C96442", initial: "C" },
  { name: "Cursor", logoUrl: "https://cursor.com/favicon.ico", color: "#1a1a1a", initial: "C" },
  { name: "Windsurf", logoUrl: "https://windsurf.com/favicon.ico", color: "#00897B", initial: "W" },
  { name: "Cline", logoUrl: "https://avatars.githubusercontent.com/u/184127137?v=4", color: "#2563EB", initial: "C" },
  { name: "OpenCode", logoUrl: "https://opencode.ai/favicon.ico", color: "#EA580C", initial: "O" },
];

function ClientMark({ logoUrl, color, initial }: { logoUrl: string; color: string; initial: string }) {
  const [err, setErr] = useState(false);
  if (!logoUrl || err) {
    return <span className="zmcp-client-chip-mark" style={{ background: color }}>{initial}</span>;
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={logoUrl} alt="" className="zmcp-client-chip-mark-img" onError={() => setErr(true)} />
  );
}

export function LandingClientWrapper() {
  const router = useRouter();

  const [pending, setPending] = useState<OAuthProvider | null>(null);
  const [slow, setSlow] = useState(false);
  const [errorNotice, setErrorNotice] = useState<string | null>(null);
  const [loginOpen, setLoginOpen] = useState(false);

  useEffect(() => {
    if (!loginOpen) return;
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && setLoginOpen(false);
    document.addEventListener("keydown", onEsc);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onEsc);
      document.body.style.overflow = prevOverflow;
    };
  }, [loginOpen]);

  useEffect(() => {
    captureZyndOAuthReq();
    const search = new URLSearchParams(window.location.search);
    const hash = window.location.hash;
    if (search.get("error") || hash.includes("error=")) {
      setErrorNotice("That didn't go through. Try again?");
    }
  }, []);

  useEffect(() => {
    const sb = getSupabase();
    const {
      data: { subscription },
    } = sb.auth.onAuthStateChange((event, session) => {
      if (
        session &&
        (event === "SIGNED_IN" || event === "TOKEN_REFRESHED" || event === "INITIAL_SESSION")
      ) {
        if (window.location.hash) {
          window.history.replaceState(null, "", window.location.pathname);
        }
        router.replace("/dashboard");
      }
    });
    sb.auth.getSession().then(({ data: { session } }) => {
      if (session) router.replace("/dashboard");
    });
    return () => subscription.unsubscribe();
  }, [router]);

  useEffect(() => {
    if (!pending) { setSlow(false); return; }
    const t = setTimeout(() => setSlow(true), 3000);
    return () => clearTimeout(t);
  }, [pending]);

  const handleOAuth = async (provider: OAuthProvider) => {
    setPending(provider);
    setErrorNotice(null);
    const sb = getSupabase();
    const { error } = await sb.auth.signInWithOAuth({
      provider,
      options: { redirectTo: window.location.origin },
    });
    if (error) {
      setPending(null);
      setErrorNotice("That didn't go through. Try again?");
    }
  };

  const scrollTo = (id: string) => (e: React.MouseEvent<HTMLAnchorElement>) => {
    e.preventDefault();
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <>
      <main className="zlanding">
        <nav className="zlanding-nav">
          <div className="zlanding-nav-inner">
            <div className="zln-brand">
              <Monogram size="sm" />
              <span className="zln-brand-text">ZyndAI Persona</span>
              <span className="zln-version">v1.0</span>
            </div>
            <div className="zln-links">
              <a href="#how" onClick={scrollTo("how")}>How it works</a>
              <a href="#connect" onClick={scrollTo("connect")}>Connect anywhere</a>
              <a href="#why" onClick={scrollTo("why")}>Why Zynd</a>
              <a href="#start" onClick={scrollTo("start")}>Get started</a>
            </div>
            <div className="zln-cta">
              <button
                type="button"
                className="zln-login-btn"
                disabled={pending !== null}
                aria-haspopup="dialog"
                aria-expanded={loginOpen}
                onClick={() => setLoginOpen(true)}
              >
                Log in
              </button>
            </div>
          </div>
        </nav>

        <div className="zlanding-hero-panel">
          <div className="zlanding-bg" aria-hidden="true" />

          <section className="zhero">
            <h1 className="zhero-title">
              Networking, but only
              <br />
              <span className="zhero-title-em">the part you actually like.</span>
            </h1>

            <p className="zhero-sub">
              Your Persona finds people worth meeting, reaches out on your behalf,
              and books the times. You just show up.
            </p>

            <div className="zhero-cta-row" id="start">
              <button
                type="button"
                className="zhero-cta primary"
                disabled={pending !== null}
                onClick={() => handleOAuth("linkedin_oidc")}
              >
                <LinkedInLogo size={18} />
                <span>
                  {pending === "linkedin_oidc" && slow ? "still going…" : "Continue with LinkedIn"}
                </span>
              </button>
            </div>

            {errorNotice && !pending && (
              <div className="zhero-notice">{errorNotice}</div>
            )}

            <div className="zhero-images" aria-hidden="true">
              <div className="zhero-img zhero-img-left">
                <img src="/hero-left.png" alt="" loading="lazy" />
              </div>
              <div className="zhero-img zhero-img-main">
                <img src="/hero-main.png" alt="" loading="lazy" />
              </div>
              <div className="zhero-img zhero-img-right">
                <img src="/hero-right.png" alt="" loading="lazy" />
              </div>
            </div>
          </section>

          <section className="zfeatures" id="how">
            <div className="zfeatures-head">
              <div className="zfeatures-pill">
                <img src="/highlights/top-eye.svg" alt="" loading="lazy" />
                <span>HOW IT WORKS</span>
              </div>
              <h2 className="zfeatures-title">
                Three steps to <span className="zfeatures-title-em">meaningful meetings</span>
              </h2>
              <p className="zfeatures-sub">
                From outreach to calendar, your Persona handles every part of your networking workflow
                in one place. No cold DMs, no calendar tetris—just the people worth meeting.
              </p>
            </div>
            <div className="zfeatures-grid">
              <article className="zfeature">
                <div className="zfeature-icon zfeature-icon-1">
                  <img src="/highlights/icon-1.svg" alt="" loading="lazy" />
                </div>
                <h3 className="zfeature-title">Finds people worth meeting</h3>
                <p className="zfeature-body">
                  Reads your posts, scans the network, surfaces few people worth a coffee.
                </p>
              </article>
              <article className="zfeature">
                <div className="zfeature-icon zfeature-icon-2">
                  <img src="/highlights/icon-2.svg" alt="" loading="lazy" />
                </div>
                <h3 className="zfeature-title">Reaches out so you don&apos;t have to</h3>
                <p className="zfeature-body">
                  No cold DMs. Your agent talks to their agent first.
                </p>
              </article>
              <article className="zfeature">
                <div className="zfeature-icon zfeature-icon-3">
                  <img src="/highlights/icon-3.svg" alt="" loading="lazy" />
                </div>
                <h3 className="zfeature-title">Books the meeting</h3>
                <p className="zfeature-body">
                  You approve a time, your Persona puts it on your calendar.
                </p>
              </article>
            </div>
          </section>

          <section className="zfeatures zmcp" id="connect">
            <div className="zfeatures-head">
              <div className="zfeatures-pill">
                <Plug size={16} color="#6366f1" strokeWidth={2.25} />
                <span>PLUGS INTO YOUR AI</span>
              </div>
              <h2 className="zfeatures-title">
                Your Persona, wherever
                <span className="zfeatures-title-em">you already talk to AI.</span>
              </h2>
              <p className="zfeatures-sub">
                Connect once over MCP and Claude, Cursor, Windsurf, or any AI client can check
                your calendar, draft the follow-up, or reach out on your behalf — without you
                switching tabs.
              </p>
            </div>
            <div className="zfeatures-grid zmcp-grid">
              <article className="zfeature">
                <div className="zfeature-icon zfeature-icon-4">
                  <Plug size={30} color="#ffffff" strokeWidth={1.75} />
                </div>
                <h3 className="zfeature-title">One connection, your whole toolkit</h3>
                <p className="zfeature-body">
                  Calendar, Gmail, Docs, Notion, LinkedIn — all reachable through a single MCP
                  server, so there&apos;s nothing extra to log into.
                </p>
              </article>
              <article className="zfeature">
                <div className="zfeature-icon zfeature-icon-5">
                  <MessageSquareText size={30} color="#ffffff" strokeWidth={1.75} />
                </div>
                <h3 className="zfeature-title">Ask the AI you already use</h3>
                <p className="zfeature-body">
                  Claude, Cursor, Windsurf, Cline — point any MCP client at Zynd and it&apos;s
                  talking straight to your Persona, not a generic plugin.
                </p>
              </article>
              <article className="zfeature">
                <div className="zfeature-icon zfeature-icon-6">
                  <Waypoints size={30} color="#ffffff" strokeWidth={1.75} />
                </div>
                <h3 className="zfeature-title">Agents that talk to agents</h3>
                <p className="zfeature-body">
                  Your Persona can reach someone else&apos;s Persona directly over MCP — the
                  outreach happens agent to agent, before either of you says a word.
                </p>
              </article>
              <article className="zfeature">
                <div className="zfeature-icon zfeature-icon-7">
                  <FileOutput size={30} color="#ffffff" strokeWidth={1.75} />
                </div>
                <h3 className="zfeature-title">Publish pages straight from chat</h3>
                <p className="zfeature-body">
                  Ask it to write something up and it&apos;s live at a shareable URL in seconds —
                  public, unlisted, or just for you. No hosting, no deploy.
                </p>
              </article>
            </div>
            <div className="zmcp-clients">
              <span className="zmcp-clients-label">Connect from</span>
              <div className="zmcp-clients-row">
                {MCP_CLIENTS.map((c) => (
                  <span className="zmcp-client-chip" key={c.name}>
                    <ClientMark logoUrl={c.logoUrl} color={c.color} initial={c.initial} />
                    {c.name}
                  </span>
                ))}
                <span className="zmcp-client-chip zmcp-client-chip-more">+ any MCP client</span>
              </div>
            </div>
          </section>

          <section className="zwhy" id="why">
            <p className="zwhy-eyebrow">Why Zynd</p>
            <h2 className="zwhy-title">
              The good parts of networking, without the awkward ones.
            </h2>
            <p className="zwhy-body">
              Zynd is a personal AI agent for the part of professional life everyone
              quietly hates: cold outreach, calendar tetris, the small talk before
              the small talk. Your Persona does it on your behalf — politely, and in
              your voice.
            </p>
          </section>
        </div>

        <footer className="zlanding-footer">
          <span style={{ fontWeight: 600, color: "#0f172a" }}>ZyndAI Persona</span>
          <span>Built for the networking you&apos;d actually enjoy.</span>
          <div className="zlanding-footer-links">
            <a href="/terms">Terms</a>
            <span>·</span>
            <a href="/privacy">Privacy</a>
            <span>·</span>
            <span>© Zynd</span>
          </div>
        </footer>

        {loginOpen && (
          <div
            className="zln-modal-backdrop"
            role="dialog"
            aria-modal="true"
            aria-labelledby="zln-modal-title"
            onClick={() => setLoginOpen(false)}
          >
            <div className="zln-modal" onClick={(e) => e.stopPropagation()}>
              <button
                type="button"
                className="zln-modal-close"
                aria-label="Close"
                onClick={() => setLoginOpen(false)}
              >
                <X size={18} strokeWidth={1.7} />
              </button>
              <div className="zln-modal-mark">
                <Monogram size="md" />
              </div>
              <h2 id="zln-modal-title" className="zln-modal-title">
                Welcome back
              </h2>
              <p className="zln-modal-sub">
                Continue with your LinkedIn account. We&apos;ll only ever read what you let us.
              </p>
              <div className="zln-modal-options">
                <button
                  type="button"
                  className="zln-modal-option"
                  disabled={pending !== null}
                  onClick={() => handleOAuth("linkedin_oidc")}
                >
                  <LinkedInLogo />
                  <span>
                    {pending === "linkedin_oidc" && slow ? "Still going…" : "Continue with LinkedIn"}
                  </span>
                </button>
              </div>
              <p className="zln-modal-foot">
                By continuing you agree to our{" "}
                <a href="/terms">Terms</a> and <a href="/privacy">Privacy</a>.
              </p>
            </div>
          </div>
        )}
      </main>
    </>
  );
}
