"use client";

/**
 * Cards login — Google, LinkedIn, and email magic link (per
 * ZYND_CARDS_MOVE_PLAN.md §1). No GitHub: that's the dashboard's provider
 * set, not ours.
 */

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { setAuthNext } from "@/lib/auth/next-cookie";

function AuthPageContent() {
  const searchParams = useSearchParams();
  const error = searchParams.get("error");
  const [email, setEmail] = useState("");
  const [magicLinkSent, setMagicLinkSent] = useState(false);
  const [sending, setSending] = useState(false);

  const loginRedirect = `${typeof window !== "undefined" ? window.location.origin : ""}/auth/callback`;

  const withNextCookie = () => {
    const next =
      typeof window !== "undefined"
        ? searchParams.get("next") || "/directory"
        : "/directory";
    setAuthNext(next);
  };

  const loginWithGoogle = () => {
    withNextCookie();
    createClient().auth.signInWithOAuth({ provider: "google", options: { redirectTo: loginRedirect } });
  };

  const loginWithLinkedin = () => {
    withNextCookie();
    createClient().auth.signInWithOAuth({ provider: "linkedin_oidc", options: { redirectTo: loginRedirect } });
  };

  const sendMagicLink = async () => {
    if (!email.trim()) return;
    withNextCookie();
    setSending(true);
    try {
      const { error: otpError } = await createClient().auth.signInWithOtp({
        email: email.trim(),
        options: { emailRedirectTo: loginRedirect },
      });
      if (!otpError) setMagicLinkSent(true);
    } finally {
      setSending(false);
    }
  };

  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      backgroundColor: "#000",
      fontFamily: "sans-serif",
      color: "#fff",
    }}>
      <div style={{ textAlign: "center", maxWidth: "400px", padding: "40px" }}>
        <h1 style={{ fontSize: "32px", marginBottom: "20px", fontWeight: 700 }}>
          Sign in to <span style={{ color: "#8B5CF6" }}>Zynd Cards</span>
        </h1>

        {error && (
          <p style={{ color: "#f87171", fontSize: "14px", marginBottom: "16px" }}>
            Sign-in failed — please try again.
          </p>
        )}

        <button
          onClick={loginWithGoogle}
          style={{
            width: "100%", padding: "12px 20px", marginBottom: "12px",
            backgroundColor: "#fff", color: "#000", border: "none", borderRadius: "8px",
            fontSize: "16px", fontWeight: 600, cursor: "pointer",
          }}
        >
          Sign in with Google
        </button>

        <button
          onClick={loginWithLinkedin}
          style={{
            width: "100%", padding: "12px 20px", marginBottom: "20px",
            backgroundColor: "#0A66C2", color: "#fff", border: "none", borderRadius: "8px",
            fontSize: "16px", fontWeight: 600, cursor: "pointer",
          }}
        >
          Sign in with LinkedIn
        </button>

        <div style={{ display: "flex", alignItems: "center", gap: "10px", margin: "8px 0 16px", color: "#666" }}>
          <div style={{ flex: 1, height: 1, background: "#333" }} />
          <span style={{ fontSize: "13px" }}>or</span>
          <div style={{ flex: 1, height: 1, background: "#333" }} />
        </div>

        {magicLinkSent ? (
          <p style={{ fontSize: "14px", color: "#a5b4fc" }}>
            Check your inbox — we sent a sign-in link to {email}.
          </p>
        ) : (
          <>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              style={{
                width: "100%", padding: "12px 16px", marginBottom: "10px",
                backgroundColor: "#111", color: "#fff", border: "1px solid #333",
                borderRadius: "8px", fontSize: "15px", boxSizing: "border-box",
              }}
            />
            <button
              onClick={sendMagicLink}
              disabled={sending || !email.trim()}
              style={{
                width: "100%", padding: "12px 20px",
                backgroundColor: "#1f2937", color: "#fff", border: "1px solid #374151",
                borderRadius: "8px", fontSize: "16px", fontWeight: 600,
                cursor: sending ? "default" : "pointer", opacity: sending ? 0.6 : 1,
              }}
            >
              {sending ? "Sending…" : "Email me a sign-in link"}
            </button>
          </>
        )}

        <p style={{ marginTop: "20px", fontSize: "14px", color: "#999" }}>
          Secure authentication powered by Supabase
        </p>
      </div>
    </div>
  );
}

export default function AuthPage() {
  return (
    <Suspense fallback={null}>
      <AuthPageContent />
    </Suspense>
  );
}
