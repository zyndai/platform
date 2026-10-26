"use client";

/**
 * Cards login — LinkedIn only (D12: persona's login, no Google/GitHub/magic
 * link). Magic link comes back once an email provider (SMTP) is chosen.
 *
 * Drawn in the product's look (the directory's `.dc` canvas) because that is
 * where the "Sign in" buttons that lead here live.
 */

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { EDITION_FONT_VARS } from "@/components/editions/fonts";
import { startLinkedInOAuth } from "@/lib/auth/session";
import "@/components/discover/discover.css";
import "./auth.css";

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

function AuthPageContent() {
  const searchParams = useSearchParams();
  const next = searchParams.get("next") || "";
  const [oauthError, setOauthError] = useState<string | null>(searchParams.get("error"));

  const loginWithLinkedin = async () => {
    const next = searchParams.get("next") || "/directory";
    const message = await startLinkedInOAuth(next);
    if (message) setOauthError(message);
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

            {oauthError && (
              <p role="alert" className="da-error">
                {oauthError === "auth_callback_failed" ? "Sign-in failed — please try again." : oauthError}
              </p>
            )}

            <button type="button" onClick={loginWithLinkedin} className="dc-btn da-provider">
              <LinkedInIcon />
              Sign in with LinkedIn
            </button>

            {next.startsWith("/review/") && (
              <p className="da-reviewer">
                <Link href={`/auth/reviewer?next=${encodeURIComponent(next)}`} className="dc-linkbtn">
                  Reviewer sign-in
                </Link>
              </p>
            )}

            <p className="da-note">Secure authentication powered by Supabase</p>
            <p className="da-fine">
              You&apos;ll be redirected to LinkedIn to sign in. Zynd never sees or stores
              your LinkedIn password.
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
