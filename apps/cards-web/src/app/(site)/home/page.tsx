import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import {
  ownerHomeEnabled,
  ownerRequest,
  type OwnerStatus,
} from "@/lib/owner-home";
import { OwnerHome } from "./owner-home";
import { introsEnabled, type Intro } from "@/lib/intros";
import { IntroInbox } from "@/components/intros/IntroInbox";
import "./owner-home.css";

export const metadata = {
  title: "Your home · Zynd Cards",
  robots: { index: false, follow: false },
};
export const dynamic = "force-dynamic";

export default async function HomePage() {
  if (!ownerHomeEnabled) notFound();
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session?.access_token) redirect("/auth?next=/home");
  let data: OwnerStatus | null;
  try {
    data = await ownerRequest<OwnerStatus | null>(
      "mine/status",
      session.access_token,
    );
  } catch {
    return (
      <main className="oh-page oh oh-fallback">
        <div className="oh-shell oh-panel">
          <h1>Your home is temporarily unavailable</h1>
          <p>Please try again shortly.</p>
          <Link className="oh-button" href="/home">Try again</Link>
        </div>
      </main>
    );
  }
  if (!data)
    return (
      <main className="oh-page oh oh-fallback">
        <div className="oh-shell oh-panel">
          <h1>Welcome home</h1>
          <p>Create your card to start seeing how people find you.</p>
          <Link className="oh-button" href="/create">Create your card →</Link>
        </div>
      </main>
    );
  let intros: Intro[] | null = null;
  if (introsEnabled) {
    try { intros = (await ownerRequest<{ intros: Intro[] }>("mine/intros", session.access_token)).intros; }
    catch { /* Intro outage must not hide the rest of owner home. */ }
  }
  return (
    <div className="oh-page">
      {/* Match the typography used on public profile cards. */}
      {/* eslint-disable-next-line @next/next/no-page-custom-font */}
      <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700;800&family=Space+Mono:wght@400;700&display=swap" />
      <OwnerHome initial={data} token={session.access_token} />
      {introsEnabled && (
        <div className="oh-intro-section">
          <IntroInbox initial={intros} token={session.access_token} />
        </div>
      )}
    </div>
  );
}
