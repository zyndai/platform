import type { Metadata } from "next";
import Link from "next/link";
import { CraneLit, TopBar } from "@/components/dear/ui";

export const metadata: Metadata = { title: "Sign in" };

/**
 * Sign in. The current site offers LinkedIn only; the strategy picked
 * AI-native builders as the first audience, so GitHub and Google are offered
 * too. LinkedIn stays the way to claim a page that was built from LinkedIn.
 * Buttons are inert on this branch.
 */
export default function SignIn() {
  return (
    <div className="shell narrow">
      <TopBar current="/dear/signin" />
      <div className="paper stack-lg" style={{ alignItems: "flex-start" }}>
        <CraneLit className="crane-hero" />
        <h1 className="display" style={{ fontSize: "clamp(40px, 7vw, 60px)" }}>
          Welcome back.
        </h1>
        <p className="dim" style={{ fontSize: 23 }}>
          Sign in to read what your agent pencilled in, and to answer the people who said hello.
        </p>
        <div className="stack" style={{ width: "100%", maxWidth: 360 }}>
          <Link href="/dear/home" className="btn">
            Continue with GitHub
          </Link>
          <Link href="/dear/home" className="btn quiet">
            Continue with LinkedIn
          </Link>
          <Link href="/dear/home" className="btn quiet">
            Continue with Google
          </Link>
        </div>
        <p className="m dim">No password. We never post anything, anywhere, in your name.</p>
        <hr style={{ width: "100%" }} />
        <p style={{ fontSize: 22 }}>
          No letter yet?{" "}
          <Link href="/dear/write" style={{ color: "var(--agent)" }}>
            Write yours
          </Link>
          . It takes about two minutes and you do not need an account to start.
        </p>
      </div>
    </div>
  );
}
