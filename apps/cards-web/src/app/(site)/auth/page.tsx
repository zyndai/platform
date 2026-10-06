"use client";

/**
 * Cards login — LinkedIn only (D12: persona's login, no Google/GitHub/magic
 * link). Magic link comes back once an email provider (SMTP) is chosen.
 */

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { startLinkedInOAuth } from "@/lib/auth/session";

function AuthPageContent() {
  const searchParams = useSearchParams();
  const [oauthError, setOauthError] = useState<string | null>(searchParams.get("error"));

  const loginWithLinkedin = async () => {
    const next = searchParams.get("next") || "/directory";
    const message = await startLinkedInOAuth(next);
    if (message) setOauthError(message);
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

        {oauthError && (
          <p style={{ color: "#f87171", fontSize: "14px", marginBottom: "16px" }}>
            Sign-in failed — please try again.
          </p>
        )}

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

        <p style={{ marginTop: "20px", fontSize: "14px", color: "#999" }}>
          Secure authentication powered by Supabase
        </p>
        <p style={{ marginTop: "8px", fontSize: "12px", color: "#666", lineHeight: 1.5 }}>
          You&apos;ll be redirected to LinkedIn to sign in. Zynd never sees or stores
          your LinkedIn password.
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
