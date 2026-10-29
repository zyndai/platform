"use client";

import { useId, useState, type FormEvent } from "react";
import { useSignInMethods } from "@/hooks/useSignInMethods";
import { MAX_EMAIL_LENGTH, isPlausibleEmail, sendMagicLink, startGoogleOAuth } from "@/lib/auth/session";
import { shareClaimIntentAcrossTabs } from "@/lib/claim-tokens";
import "./alternate-sign-in.css";

/** Google returns to this tab; an email magic link opens a new one, so anything
 *  saved for the return trip must outlive this tab's sessionStorage. */
export type AlternateSignInMethod = "google" | "email";

interface SignInTarget {
  /** Path to land on after sign-in. Sanitized again by the callback. */
  next: string;
  intent?: "card";
  /** Runs right before the sign-in starts (e.g. to save a draft or claim handle). */
  onBeforeSignIn?: (method: AlternateSignInMethod) => void;
}

interface AlternateSignInProps extends SignInTarget {
  /** Matches the surface's LinkedIn button so the options look like one set. */
  buttonClassName: string;
}

/**
 * Google and email magic-link sign-in, rendered under a surface's LinkedIn
 * button. LinkedIn stays the default (D12); each option shows only when
 * lib/auth/providers.ts allows it, and nothing renders when neither is.
 * Must sit inside the `.dc` canvas, whose tokens the styles use.
 */
export function AlternateSignIn({ buttonClassName, ...target }: AlternateSignInProps) {
  const { google, email } = useSignInMethods();
  if (!google && !email) return null;
  return (
    <div className="zas">
      {google && <GoogleSignInButton className={buttonClassName} {...target} />}
      {email && <EmailLinkForm buttonClassName={buttonClassName} {...target} />}
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#4285F4" d="M23.5 12.27c0-.82-.07-1.6-.2-2.36H12v4.47h6.45a5.52 5.52 0 01-2.4 3.62v3h3.88c2.27-2.09 3.57-5.17 3.57-8.73z" />
      <path fill="#34A853" d="M12 24c3.24 0 5.96-1.07 7.94-2.9l-3.88-3c-1.07.72-2.45 1.15-4.06 1.15-3.12 0-5.77-2.11-6.71-4.95H1.28v3.1A12 12 0 0012 24z" />
      <path fill="#FBBC05" d="M5.29 14.3a7.2 7.2 0 010-4.6V6.6H1.28a12 12 0 000 10.8l4.01-3.1z" />
      <path fill="#EA4335" d="M12 4.75c1.76 0 3.34.6 4.59 1.8l3.44-3.44A11.97 11.97 0 0012 0 12 12 0 001.28 6.6l4.01 3.1C6.23 6.86 8.88 4.75 12 4.75z" />
    </svg>
  );
}

function GoogleSignInButton({ className, next, intent, onBeforeSignIn }: SignInTarget & { className: string }) {
  const [redirecting, setRedirecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signIn() {
    setRedirecting(true);
    setError(null);
    onBeforeSignIn?.("google");
    try {
      const message = await startGoogleOAuth(next, intent);
      if (message) {
        setError(message);
        setRedirecting(false);
      }
    } catch (err) {
      console.error("[GoogleSignInButton] sign-in failed:", err);
      setError("Couldn't start Google sign-in. Try again.");
      setRedirecting(false);
    }
  }

  return (
    <>
      <button type="button" onClick={signIn} disabled={redirecting} className={className}>
        <GoogleIcon />
        {redirecting ? "Redirecting…" : "Continue with Google"}
      </button>
      {error && <p role="alert" className="zas-error">{error}</p>}
    </>
  );
}

type EmailStatus =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "sent"; to: string }
  | { kind: "error"; message: string };

function EmailLinkForm({ buttonClassName, next, intent, onBeforeSignIn }: SignInTarget & { buttonClassName: string }) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<EmailStatus>({ kind: "idle" });
  const inputId = useId();
  const errorId = `${inputId}-error`;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (status.kind === "sending") return;
    const address = email.trim();
    if (!isPlausibleEmail(address)) {
      setStatus({ kind: "error", message: "Enter a valid email address." });
      return;
    }
    setStatus({ kind: "sending" });
    onBeforeSignIn?.("email");
    shareClaimIntentAcrossTabs();
    const message = await sendMagicLink(address, next, intent);
    setStatus(message ? { kind: "error", message } : { kind: "sent", to: address });
  }

  const sending = status.kind === "sending";
  const sent = status.kind === "sent";
  // The status region stays mounted from first render so screen readers
  // announce the "check your email" text when it appears in it.
  return (
    <div>
      <div className={sent ? "zas-sent" : undefined}>
        <div role="status" aria-live="polite">
          {sent && (
            <p>
              Check <strong>{status.to}</strong> for a sign-in link. Open it in this browser to
              finish signing in. The link expires in an hour.
            </p>
          )}
        </div>
        {sent && (
          <button type="button" className="zas-link" onClick={() => setStatus({ kind: "idle" })}>
            Use a different email
          </button>
        )}
      </div>
      {!sent && (
        <form className="zas-form" onSubmit={submit} noValidate>
          <div className="zas-or" aria-hidden="true"><span>or</span></div>
          <label className="zas-label" htmlFor={inputId}>Email</label>
          <input
            id={inputId}
            className="zas-input"
            type="email"
            inputMode="email"
            autoComplete="email"
            autoCapitalize="off"
            spellCheck={false}
            placeholder="you@example.com"
            maxLength={MAX_EMAIL_LENGTH}
            value={email}
            aria-invalid={status.kind === "error"}
            aria-describedby={status.kind === "error" ? errorId : undefined}
            onChange={(e) => {
              setEmail(e.target.value);
              if (status.kind === "error") setStatus({ kind: "idle" });
            }}
          />
          {status.kind === "error" && (
            <p id={errorId} role="alert" className="zas-error">{status.message}</p>
          )}
          <button type="submit" disabled={sending} className={buttonClassName}>
            {sending ? "Sending…" : "Email me a sign-in link"}
          </button>
        </form>
      )}
    </div>
  );
}
