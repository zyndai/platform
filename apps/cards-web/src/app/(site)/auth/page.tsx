"use client";

/**
 * Cards login: Google, LinkedIn, or a 6-digit code sent to an email address.
 * Every "Sign in" and "Claim" button on the site sends people here, so the
 * choice of method lives in one place. This reverses D12 (LinkedIn only):
 * people often want to sign in with a different account than the one their
 * card was built from, and claiming no longer depends on which one they use.
 *
 * Drawn in the product's look (the directory's `.dc` canvas) because that is
 * where the "Sign in" buttons that lead here live.
 */

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { EDITION_FONT_VARS } from "@/components/editions/fonts";
import { sendEmailCode, startOAuth, verifyEmailCode, type OAuthProvider } from "@/lib/auth/session";
import { safeNextPath } from "@/lib/auth/next-cookie";
import { clientOrigin } from "@/lib/auth/origin";
import "@/components/discover/discover.css";
import "./auth.css";

const DEFAULT_NEXT = "/directory";
const CODE_LENGTH = 6;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function LinkedInIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <rect width="24" height="24" rx="4" fill="#0A66C2" />
      <path
        fill="#fff"
        d="M7.1 9.6h2.4V18H7.1V9.6zm1.2-3.9a1.4 1.4 0 110 2.8 1.4 1.4 0 010-2.8zM11.2 9.6h2.3v1.15h.03c.32-.6 1.1-1.25 2.27-1.25 2.43 0 2.88 1.6 2.88 3.68V18h-2.4v-4.3c0-1.03-.02-2.35-1.43-2.35-1.44 0-1.65 1.12-1.65 2.28V18h-2.4V9.6z"
      />
    </svg>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#4285F4" d="M23.49 12.27c0-.79-.07-1.54-.19-2.27H12v4.51h6.47c-.29 1.48-1.14 2.73-2.4 3.58v3h3.86c2.26-2.09 3.56-5.17 3.56-8.82z" />
      <path fill="#34A853" d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.86-3c-1.08.72-2.45 1.16-4.07 1.16-3.13 0-5.78-2.11-6.73-4.96H1.29v3.09C3.26 21.3 7.31 24 12 24z" />
      <path fill="#FBBC05" d="M5.27 14.29c-.25-.72-.38-1.49-.38-2.29s.14-1.57.38-2.29V6.62H1.29C.47 8.24 0 10.06 0 12s.47 3.76 1.29 5.38l3.98-3.09z" />
      <path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.31 0 3.26 2.7 1.29 6.62l3.98 3.09C6.22 6.86 8.87 4.75 12 4.75z" />
    </svg>
  );
}

function AuthPageContent() {
  const searchParams = useSearchParams();
  const next = safeNextPath(searchParams.get("next")) || DEFAULT_NEXT;
  const [error, setError] = useState<string | null>(searchParams.get("error"));
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [codeSentTo, setCodeSentTo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const signInWith = async (provider: OAuthProvider) => {
    setError(null);
    const message = await startOAuth(provider, next);
    if (message) setError(message);
  };

  const sendCode = async (event?: React.FormEvent) => {
    event?.preventDefault();
    const address = email.trim().toLowerCase();
    if (!EMAIL_RE.test(address)) {
      setError("Enter a valid email address.");
      return;
    }
    setBusy(true);
    setError(null);
    const message = await sendEmailCode(address);
    setBusy(false);
    if (message) {
      setError(message);
      return;
    }
    setCode("");
    setCodeSentTo(address);
  };

  const verifyCode = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!codeSentTo) return;
    const digits = code.replace(/\D/g, "");
    if (digits.length !== CODE_LENGTH) {
      setError(`Enter the ${CODE_LENGTH}-digit code from the email.`);
      return;
    }
    setBusy(true);
    setError(null);
    const message = await verifyEmailCode(codeSentTo, digits);
    if (message) {
      setError("That code didn't work. Check it, or send a new one.");
      setBusy(false);
      return;
    }
    // Full navigation so server components read the new session cookies.
    window.location.assign(new URL(next, clientOrigin()).toString());
  };

  return (
    <main className={`dc ${EDITION_FONT_VARS}`}>
      <div className="dc-wrap">
        <header className="dc-header">
          <div className="dc-crumbs">
            <Link href="/">Zynd</Link>
            {" / "}
            <strong>Sign in</strong>
          </div>
        </header>

        <section className="da-stage">
          <div className="da-panel">
            <div role="heading" aria-level={1} className="da-title">
              Sign in to <span>Zynd Cards</span>
            </div>

            {error && (
              <p role="alert" className="da-error">
                {error === "auth_callback_failed" ? "Sign-in failed — please try again." : error}
              </p>
            )}

            {codeSentTo ? (
              <form onSubmit={verifyCode} className="da-email">
                <p className="da-sent">
                  We sent a {CODE_LENGTH}-digit code to <strong>{codeSentTo}</strong>.
                </p>
                <label htmlFor="da-code" className="dc-sr">Sign-in code</label>
                <input
                  id="da-code"
                  className="da-input da-code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9]*"
                  maxLength={CODE_LENGTH}
                  placeholder="123456"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  autoFocus
                />
                <button type="submit" className="dc-btn dc-btn-primary da-submit" disabled={busy}>
                  {busy ? "Signing in…" : "Sign in"}
                </button>
                <div className="da-row">
                  <button type="button" className="dc-linkbtn" disabled={busy} onClick={() => void sendCode()}>
                    Send a new code
                  </button>
                  <button
                    type="button"
                    className="dc-linkbtn"
                    disabled={busy}
                    onClick={() => { setCodeSentTo(null); setCode(""); setError(null); }}
                  >
                    Use a different email
                  </button>
                </div>
              </form>
            ) : (
              <>
                <div className="da-providers">
                  <button type="button" onClick={() => void signInWith("google")} className="dc-btn da-provider">
                    <GoogleIcon />
                    Continue with Google
                  </button>
                  <button type="button" onClick={() => void signInWith("linkedin_oidc")} className="dc-btn da-provider">
                    <LinkedInIcon />
                    Continue with LinkedIn
                  </button>
                </div>

                <div className="da-or" aria-hidden="true"><span>or</span></div>

                <form onSubmit={sendCode} className="da-email">
                  <label htmlFor="da-email" className="dc-sr">Email address</label>
                  <input
                    id="da-email"
                    className="da-input"
                    type="email"
                    autoComplete="email"
                    placeholder="you@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                  <button type="submit" className="dc-btn dc-btn-primary da-submit" disabled={busy}>
                    {busy ? "Sending…" : "Email me a code"}
                  </button>
                </form>
              </>
            )}

            {next.startsWith("/review/") && (
              <p className="da-reviewer">
                <Link href={`/auth/reviewer?next=${encodeURIComponent(next)}`} className="dc-linkbtn">
                  Reviewer sign-in
                </Link>
              </p>
            )}

            <p className="da-note">Secure authentication powered by Supabase</p>
            <p className="da-fine">
              Use any of these. You can claim your card whichever one you pick, and
              connect the others later from your home page.
            </p>
          </div>
        </section>
      </div>
    </main>
  );
}

export default function AuthPage() {
  return (
    <Suspense fallback={null}>
      <AuthPageContent />
    </Suspense>
  );
}
