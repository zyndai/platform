"use client";

/**
 * Email + password sign-in for the demo account given to OpenAI's plugin
 * reviewers, who have no LinkedIn login for it. Not in the navigation: /auth
 * links here only when the destination is a /review/ page. Supabase decides
 * who may sign in, so this form adds no access of its own.
 */

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { safeNextPath } from "@/lib/auth/next-cookie";
import { clientOrigin } from "@/lib/auth/origin";

const inputStyle = {
  width: "100%", padding: "12px 14px", marginBottom: "12px", boxSizing: "border-box",
  backgroundColor: "#111", color: "#fff", border: "1px solid #333", borderRadius: "8px",
  fontSize: "16px",
} as const;

function ReviewerSignInForm() {
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const { error: signInError } = await createClient().auth.signInWithPassword({
      email: email.trim(),
      password,
    });
    if (signInError) {
      setError("Sign-in failed. Check the email and password.");
      setBusy(false);
      return;
    }
    // Full navigation so server components read the new session cookies.
    const next = safeNextPath(searchParams.get("next")) || "/directory";
    window.location.assign(new URL(next, clientOrigin()).toString());
  };

  return (
    <div style={{
      minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
      backgroundColor: "#000", fontFamily: "sans-serif", color: "#fff",
    }}>
      <form onSubmit={submit} style={{ textAlign: "center", maxWidth: "400px", width: "100%", padding: "40px" }}>
        <h1 style={{ fontSize: "28px", marginBottom: "20px", fontWeight: 700 }}>
          Reviewer sign-in
        </h1>

        {error && (
          <p role="alert" style={{ color: "#f87171", fontSize: "14px", marginBottom: "16px" }}>{error}</p>
        )}

        <input
          type="email" required autoComplete="username" placeholder="Reviewer email"
          value={email} onChange={(e) => setEmail(e.target.value)} style={inputStyle}
        />
        <input
          type="password" required autoComplete="current-password" placeholder="Password"
          value={password} onChange={(e) => setPassword(e.target.value)} style={inputStyle}
        />
        <button
          type="submit" disabled={busy}
          style={{
            width: "100%", padding: "12px 20px", marginTop: "8px",
            backgroundColor: "#8B5CF6", color: "#fff", border: "none", borderRadius: "8px",
            fontSize: "16px", fontWeight: 600, cursor: busy ? "wait" : "pointer",
            opacity: busy ? 0.6 : 1,
          }}
        >
          Sign in
        </button>
      </form>
    </div>
  );
}

export function ReviewerSignIn() {
  return (
    <Suspense fallback={null}>
      <ReviewerSignInForm />
    </Suspense>
  );
}
