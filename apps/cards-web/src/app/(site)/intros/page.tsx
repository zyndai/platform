import { notFound, redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { ownerRequest } from "@/lib/owner-home";
import { introsEnabled, type Intro } from "@/lib/intros";
import { IntroInbox } from "@/components/intros/IntroInbox";

export const dynamic = "force-dynamic";
export const metadata = { title: "Introductions · Zynd", robots: { index: false, follow: false } };

export default async function IntrosPage({ searchParams }: { searchParams: Promise<{ outgoing?: string }> }) {
  if (!introsEnabled) notFound();
  const outgoing = (await searchParams).outgoing === "true";
  const { data: { session } } = await (await createClient()).auth.getSession();
  if (!session?.access_token) redirect(`/auth?next=${encodeURIComponent(`/intros${outgoing ? "?outgoing=true" : ""}`)}`);
  let rows: Intro[] | null = null;
  try { rows = (await ownerRequest<{ intros: Intro[] }>(`mine/intros${outgoing ? "?outgoing=true" : ""}`, session.access_token)).intros; }
  catch { /* The inbox gives a retry action. */ }
  return <main style={{ maxWidth: 800, padding: 24, margin: "auto" }}>
    <IntroInbox initial={rows} token={session.access_token} outgoing={outgoing} />
  </main>;
}
