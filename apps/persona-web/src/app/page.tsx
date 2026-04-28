"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getSupabase } from "@/lib/supabase";
import { Button, Monogram, ThinkingDot } from "@/components/ui";

type OAuthProvider = "linkedin_oidc" | "google";

export default function LandingPage() {
  const router = useRouter();

  const [checkingSession, setCheckingSession] = useState(true);
  const [pending, setPending] = useState<OAuthProvider | null>(null);
  const [slow, setSlow] = useState(false);
  const [errorNotice, setErrorNotice] = useState<string | null>(null);

  // Surface OAuth failures coming back in the URL (Supabase uses ?error=...
  // and sometimes a hash fragment; we check both). Read from window instead
  // of useSearchParams to avoid needing a Suspense boundary on the page.
  useEffect(() => {
    const search = new URLSearchParams(window.location.search);
    const hash = window.location.hash;
    if (search.get("error") || hash.includes("error=")) {
      setErrorNotice("That didn't go through. Try again?");
    }
  }, []);

  // Initial session check — already-signed-in users skip past the landing.
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

  // If a provider click hasn't redirected us within 3 seconds, we surface
  // a quiet "still going…" line instead of a spinner.
  useEffect(() => {
    if (!pending) {
      setSlow(false);
      return;
    }
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

  const scrollToOAuth = (e: React.MouseEvent<HTMLAnchorElement>) => {
    e.preventDefault();
    document
      .getElementById("oauth-col")
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  if (checkingSession) {
    return (
      <div className="boot-loader">
        <Monogram size="md" />
        <div className="line">
          <ThinkingDot />
          <span>Just a sec…</span>
        </div>
      </div>
    );
  }

  return (
    <main className="s-landing">
      <nav className="s-landing-topbar">
        <div className="brand">
          <Monogram size="sm" />
          <span className="brand-text">Zynd</span>
        </div>
        <a href="#oauth-col" onClick={scrollToOAuth} className="signin-link">
          Sign in
        </a>
      </nav>

      <section className="s-landing-hero fade-cascade">
        <Monogram size="md" className="hero-mark" />

        <h1 className="display-l">
          Help with the part of
          <br />
          networking you hate.
        </h1>

        <p className="body-l subhead">
          Aria finds people worth meeting, reaches out on your behalf,
          and books the times. You just show up.
        </p>

        <div className="oauth-col" id="oauth-col">
          <Button
            variant="primary"
            fullWidth
            disabled={pending !== null}
            className={pending === "linkedin_oidc" ? "is-dim" : ""}
            onClick={() => handleOAuth("linkedin_oidc")}
          >
            {pending === "linkedin_oidc" && slow ? "still going…" : "Continue with LinkedIn"}
          </Button>
          <Button
            variant="secondary"
            fullWidth
            disabled={pending !== null}
            className={pending === "google" ? "is-dim" : ""}
            onClick={() => handleOAuth("google")}
          >
            {pending === "google" && slow ? "still going…" : "Continue with Google"}
          </Button>
        </div>

        {errorNotice && !pending && (
          <div className="retry-notice">{errorNotice}</div>
        )}

        <div className="features">
          <div className="feature">
            <h3>Finds people worth meeting.</h3>
            <p>Reads your posts, scans the network, surfaces three humans worth a coffee.</p>
          </div>
          <div className="feature">
            <h3>Reaches out so you don&apos;t have to.</h3>
            <p>No cold DMs. Her agent talks to their agent first.</p>
          </div>
          <div className="feature">
            <h3>Books the meeting.</h3>
            <p>You approve a time, Aria puts it on your calendar.</p>
          </div>
        </div>
      </section>

      <div className="s-landing-ticker">
        324 people met someone new on Zynd this week.
      </div>
      <footer className="s-landing-footer">
        <a href="/terms">Terms</a>
        <span className="sep">·</span>
        <a href="/privacy">Privacy</a>
        <span className="sep">·</span>
        © Zynd
      </footer>
    </main>
  );
}
