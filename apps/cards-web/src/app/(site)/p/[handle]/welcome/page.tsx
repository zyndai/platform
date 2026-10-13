import type { Metadata } from "next";
import Link from "next/link";
import { ownerHomeEnabled } from "@/lib/owner-home";
import { notFound } from "next/navigation";
import { fetchCardByHandle, cardCanonicalUrl } from "@/lib/cards";
import { ProfileChatWidget, type ChatMessage } from "@/components/ProfileChatWidget";
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

/** Build a canned Q&A from the just-published card so first-win shows a working answer. */
function seedAskMessages(card: NonNullable<Awaited<ReturnType<typeof fetchCardByHandle>>>): ChatMessage[] {
  const first = (card.identity.name || "You").split(" ")[0];
  const working = (card.working_on ?? []).filter(Boolean).slice(0, 2);
  const help = (card.can_help_with ?? []).filter(Boolean).slice(0, 2);
  const location = card.identity.location?.trim();
  const fact = (card.searchable_facts ?? []).find((f) => typeof f === "string" && f.length > 12);

  const bits: string[] = [];
  if (working.length) bits.push(`building ${working.join(" and ")}`);
  if (help.length) bits.push(`can help with ${help.join(" and ")}`);
  if (location) bits.push(`based in ${location}`);

  const answer = bits.length
    ? `${first} is ${bits.join(", ")}. That's what this card knows from their public profile.`
    : fact
      ? String(fact)
      : `${first}'s card is live — ask what they're building, where they're based, or who they help.`;

  return [
    { role: "user", content: `What is ${first} working on?` },
    { role: "assistant", content: answer },
  ];
}

export default async function WelcomePage({ params }: PageProps) {
  const { handle } = await params;
  const card = await fetchCardByHandle(handle);
  if (!card) notFound();

  const claimed = card.claimed === true;
  const firstName = (card.identity.name || "You").split(" ")[0];
  const canonical = cardCanonicalUrl(card);
  const short = canonical.replace(/^https?:\/\//, "");
  const seed = claimed ? seedAskMessages(card) : [];
  const chatPrompts = [
    card.working_on?.find((item) => item.trim()) ? `What is ${firstName} building?` : "",
    card.skills?.find((skill) => skill.name.trim()) ? `What is ${firstName} good at?` : "",
    card.identity.headline?.trim() ? `What does ${firstName} do?` : "",
  ].filter(Boolean).slice(0, 3);
  const bookingLinks = [
    { label: "Calendly", url: card.calendly_url },
    { label: "Google Calendar", url: card.google_calendar_url },
  ].filter((link): link is { label: string; url: string } => !!link.url && /^https?:\/\//i.test(link.url));

  const steps = [
    {
      n: "01",
      title: "Ask your own card",
      body: "The real first win: an AI assistant answers questions about you — from this card, right now. Ask what you're building, where you're based, who you help.",
      action: "ask" as const,
    },
    {
      n: "02",
      title: "Say what you're looking for",
      body: "One line about what people should bring you — intros, users, feedback — keeps the right inbound coming.",
      action: "looking" as const,
    },
    {
      n: "03",
      title: "Share it",
      body: "This link is your living profile. Put it in your bio, signature, or QR at a meetup.",
      action: "share" as const,
    },
    {
      n: "04",
      title: "Connect your AI",
      body: "Coding agents can keep your card current — connect ZYND memory from the edit page.",
      action: "connect" as const,
    },
  ];

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

        {claimed && seed.length >= 2 && (
          <section
            data-testid="first-win-demo"
            style={{
              background: "#fff",
              border: "1px solid #E5E5DE",
              borderRadius: 18,
              padding: "18px 20px",
              marginBottom: 16,
            }}
          >
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: "#7B72E9", marginBottom: 12 }}>
              Ask your card — live demo
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div style={{ alignSelf: "flex-end", maxWidth: "85%", background: "#0B0B0B", color: "#fff", borderRadius: "16px 16px 4px 16px", padding: "9px 13px", fontSize: 13, lineHeight: 1.5 }}>
                {seed[0].content}
              </div>
              <div style={{ alignSelf: "flex-start", maxWidth: "90%", background: "#FAFAF8", border: "1px solid #E8E8E1", borderRadius: "16px 16px 16px 4px", padding: "9px 13px", fontSize: 13, lineHeight: 1.5, color: "#1a1a1a" }}>
                {seed[1].content}
              </div>
            </div>
          </section>
        )}

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
          <Link href={ownerHomeEnabled ? "/home" : `/p/${encodeURIComponent(handle)}`} style={{ color: "#7B72E9", fontSize: 14, fontWeight: 600, textDecoration: "none" }}>
            {ownerHomeEnabled ? "Go to my home →" : "View my profile →"}
          </Link>
        </div>
      </div>

      {claimed && (
        <ProfileChatWidget
          handle={card.handle ?? handle}
          personName={card.identity.name || "You"}
          initialMessages={seed}
          defaultOpen={false}
          prompts={chatPrompts}
          bookingLinks={bookingLinks}
        />
      )}
    </main>
  );
}
