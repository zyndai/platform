"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getSupabase } from "@/lib/supabase";

export default function LandingPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    const sb = getSupabase();

    const {
      data: { subscription },
    } = sb.auth.onAuthStateChange((event, session) => {
      if (
        session &&
        (event === "SIGNED_IN" ||
          event === "TOKEN_REFRESHED" ||
          event === "INITIAL_SESSION")
      ) {
        if (window.location.hash) {
          window.history.replaceState(null, "", window.location.pathname);
        }
        router.replace("/dashboard");
      }
    });

    sb.auth.getSession().then(({ data: { session } }) => {
      if (session) {
        router.replace("/dashboard");
      } else {
        setCheckingSession(false);
      }
    });

    return () => subscription.unsubscribe();
  }, [router]);

  const handleOAuthLogin = async (
    provider: "google" | "twitter" | "linkedin_oidc"
  ) => {
    setLoading(true);
    const sb = getSupabase();
    const { error } = await sb.auth.signInWithOAuth({
      provider,
      options: {
        redirectTo: window.location.origin,
      },
    });
    if (error) {
      console.error("Login error:", error.message);
      setLoading(false);
    }
  };

  if (checkingSession) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--bg-void)",
        }}
      >
        <div className="status-pill">
          <span className="status-dot" />
          <span>Initializing...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="page-bg" style={{ minHeight: "100vh", overflow: "hidden" }}>
      {/* ── Ambient glow orbs ─────────────────────────────── */}
      <div
        style={{
          position: "absolute",
          top: "-200px",
          left: "-150px",
          width: "500px",
          height: "500px",
          borderRadius: "50%",
          background:
            "radial-gradient(circle, rgba(0, 212, 180, 0.07), transparent 70%)",
          filter: "blur(80px)",
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          bottom: "-200px",
          right: "-100px",
          width: "600px",
          height: "600px",
          borderRadius: "50%",
          background:
            "radial-gradient(circle, rgba(79, 142, 247, 0.06), transparent 70%)",
          filter: "blur(100px)",
          pointerEvents: "none",
        }}
      />

      {/* ── Navbar ────────────────────────────────────────── */}
      <nav
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "20px 48px",
          position: "relative",
          zIndex: 10,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <div
            style={{
              width: "30px",
              height: "30px",
              borderRadius: "var(--r-sm)",
              background:
                "linear-gradient(135deg, var(--accent-teal), var(--accent-blue))",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: "Syne, sans-serif",
              fontWeight: 800,
              fontSize: "14px",
              color: "var(--bg-void)",
            }}
          >
            Z
          </div>
          <span
            style={{
              fontFamily: "Syne, sans-serif",
              fontSize: "16px",
              fontWeight: 700,
              letterSpacing: "0.5px",
            }}
          >
            Zynd <span style={{ color: "var(--accent-teal)" }}>AI</span>
          </span>
        </div>
        <div className="status-pill">
          <span className="status-dot" />
          Network Live
        </div>
      </nav>

      {/* ── Hero ──────────────────────────────────────────── */}
      <main
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          textAlign: "center",
          padding: "60px 24px 100px",
          position: "relative",
          zIndex: 10,
        }}
      >
        {/* Badge */}
        <div
          className="animate-fade-in-up"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "8px",
            marginBottom: "32px",
          }}
        >
          <span className="tag tag-teal" style={{ fontSize: "11px", padding: "4px 12px" }}>
            <span className="status-dot" style={{ marginRight: "4px" }} />
            Powered by the Zynd AI Network
          </span>
        </div>

        {/* Heading */}
        <h1
          className="animate-fade-in-up"
          style={{
            fontFamily: "Syne, sans-serif",
            fontSize: "clamp(2.2rem, 5.5vw, 4rem)",
            fontWeight: 800,
            lineHeight: 1.1,
            maxWidth: "750px",
            marginBottom: "20px",
            animationDelay: "0.1s",
            color: "var(--text-primary)",
          }}
        >
          Your AI-Powered{" "}
          <span
            style={{
              background:
                "linear-gradient(135deg, var(--accent-teal), var(--accent-blue))",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            Networking Agent
          </span>
        </h1>

        {/* Subtitle */}
        <p
          className="animate-fade-in-up"
          style={{
            fontFamily: "DM Sans, sans-serif",
            fontSize: "15px",
            color: "var(--text-secondary)",
            maxWidth: "550px",
            lineHeight: 1.7,
            marginBottom: "48px",
            animationDelay: "0.2s",
          }}
        >
          Connect your social accounts, calendar, and messaging — then let AI
          handle posting, scheduling, and responding on your behalf.
        </p>

        {/* Login Buttons */}
        <div
          className="animate-fade-in-up"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "12px",
            width: "100%",
            maxWidth: "360px",
            animationDelay: "0.3s",
          }}
        >
          <button
            className="btn-google"
            onClick={() => handleOAuthLogin("google")}
            disabled={loading}
            style={{ width: "100%", padding: "14px 24px" }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
              <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
              <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
              <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
            </svg>
            Continue with Google
          </button>

          <button
            className="btn-twitter"
            onClick={() => handleOAuthLogin("twitter")}
            disabled={loading}
            style={{ width: "100%", padding: "14px 24px" }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
            </svg>
            Continue with X
          </button>

          <button
            className="btn-linkedin"
            onClick={() => handleOAuthLogin("linkedin_oidc")}
            disabled={loading}
            style={{ width: "100%", padding: "14px 24px" }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
            </svg>
            Continue with LinkedIn
          </button>
        </div>

        {/* Features grid */}
        <div
          className="animate-fade-in-up"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: "16px",
            maxWidth: "800px",
            width: "100%",
            marginTop: "80px",
            animationDelay: "0.5s",
          }}
        >
          {[
            {
              icon: "📱",
              title: "Multi-Platform",
              desc: "Post to X, LinkedIn, and manage Google Calendar from one place.",
              color: "var(--accent-teal)",
            },
            {
              icon: "🤖",
              title: "AI Agent",
              desc: "Just tell the AI what to do. It handles posting, scheduling, and replies.",
              color: "var(--accent-purple)",
            },
            {
              icon: "🌐",
              title: "Zynd Network",
              desc: "Your agent is discoverable on the open Zynd AI agent network.",
              color: "var(--accent-blue)",
            },
          ].map((f, i) => (
            <div
              key={i}
              className="card"
              style={{ padding: "24px 20px", cursor: "default" }}
            >
              <div style={{ fontSize: "1.6rem", marginBottom: "12px" }}>
                {f.icon}
              </div>
              <h3
                style={{
                  fontFamily: "Syne, sans-serif",
                  fontSize: "14px",
                  fontWeight: 600,
                  marginBottom: "8px",
                  color: "var(--text-primary)",
                }}
              >
                {f.title}
              </h3>
              <p
                style={{
                  fontSize: "13px",
                  color: "var(--text-secondary)",
                  lineHeight: 1.6,
                }}
              >
                {f.desc}
              </p>
            </div>
          ))}
        </div>

        {/* Bottom mono text */}
        <p
          className="animate-fade-in-up"
          style={{
            fontFamily: "IBM Plex Mono, monospace",
            fontSize: "10px",
            letterSpacing: "1.5px",
            textTransform: "uppercase",
            color: "var(--text-muted)",
            marginTop: "48px",
            animationDelay: "0.6s",
          }}
        >
          Decentralized · Autonomous · Trustless
        </p>
      </main>
    </div>
  );
}
