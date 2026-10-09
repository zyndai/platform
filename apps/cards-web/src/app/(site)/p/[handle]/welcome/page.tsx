import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { fetchCardByHandle, cardCanonicalUrl } from "@/lib/cards";
import { ProfileChatWidget } from "@/components/ProfileChatWidget";
import { WelcomeActions } from "./welcome-actions";

export const revalidate = 60;

interface PageProps {
  params: Promise<{ handle: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { handle } = await params;
  const card = await fetchCardByHandle(handle);
  if (!card) return { title: "Welcome — Zynd", robots: { index: false, follow: false } };
  return {
    title: `Your card is live — Zynd`,
    robots: { index: false, follow: false },
  };
}

export default async function WelcomePage({ params }: PageProps) {
  const { handle } = await params;
  const card = await fetchCardByHandle(handle);
  if (!card) notFound();

  const claimed = card.claimed !== false;
  const firstName = (card.identity.name || "You").split(" ")[0];
  const canonical = cardCanonicalUrl(card);
  const short = canonical.replace(/^https?:\/\//, "");

  const steps = [
    {
      n: "01",
      title: "Ask your own card",
      body: "The real first win: an AI assistant answers questions about you — from this card, right now. Ask what you're building, where you're based, who you help.",
      action: "ask",
    },
    {
      n: "02",
      title: "Say what you're looking for",
      body: "One line about what people should bring you — intros, users, feedback — keeps the right inbound coming.",
      action: "looking",
    },
    {
      n: "03",
      title: "Share it",
      body: "This link is your living profile. Put it in your bio, signature, or QR at a meetup.",
      action: "share",
    },
    {
      n: "04",
      title: "Connect your AI",
      body: "Coding agents can keep your card current — connect ZYND memory from the edit page.",
      action: "connect",
    },
  ] as const;

  return (
    <main style={{ minHeight: "100dvh", background: "#F7F6F2", fontFamily: "system-ui, sans-serif", color: "#0B0B0B" }}>
      <style>{`
        .wv, .wv * { box-sizing: border-box; letter-spacing: normal; }
        .wv h1, .wv p { margin: 0; text-align: left; text-transform: none; }
      `}</style>
      <div className="wv" style={{ maxWidth: 720, margin: "0 auto", padding: "56px 24px 80px" }}>
        <header style={{ textAlign: "center", marginBottom: 40 }}>
          <div style={{ width: 58, height: 58, margin: "0 auto 18px", borderRadius: "50%", background: "#7B72E9", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path d="M5 12.5 10 17.5 19 7" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <h1 style={{ fontSize: 34, fontWeight: 800, letterSpacing: "-0.02em" }}>
            {firstName}, you&apos;re live
          </h1>
          <p style={{ fontSize: 15, color: "#6E6E68", marginTop: 8 }}>
            People and AI agents can find you at{" "}
            <span style={{ fontFamily: "monospace", fontSize: 13, background: "#EFEFEB", border: "1px solid #DEDED8", borderRadius: 8, padding: "3px 8px" }}>{short}</span>
          </p>
        </header>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {steps.map((s) => (
            <section key={s.n} style={{ background: "#fff", border: "1px solid #E5E5DE", borderRadius: 18, padding: "20px 22px", display: "flex", gap: 16, alignItems: "flex-start" }}>
              <span style={{ fontFamily: "monospace", fontSize: 12, color: "#7B72E9", fontWeight: 700, paddingTop: 2, flexShrink: 0 }}>{s.n}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 16, fontWeight: 700 }}>{s.title}</div>
                <p style={{ fontSize: 13.5, color: "#6E6E68", lineHeight: 1.55, marginTop: 5 }}>{s.body}</p>
                <WelcomeActions handle={handle} firstName={firstName} action={s.action} claimed={claimed} canonical={canonical} />
              </div>
            </section>
          ))}
        </div>

        <div style={{ textAlign: "center", marginTop: 36 }}>
          <Link href={`/p/${encodeURIComponent(handle)}`} style={{ color: "#7B72E9", fontSize: 14, fontWeight: 600, textDecoration: "none" }}>
            View my profile →
          </Link>
        </div>
      </div>

      {claimed && <ProfileChatWidget handle={card.handle ?? handle} personName={card.identity.name || "You"} />}
    </main>
  );
}