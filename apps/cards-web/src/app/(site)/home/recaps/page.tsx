import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { ownerRequest } from "@/lib/owner-home";
import type { RecapHome } from "@/lib/recaps";
import { RecapEditor } from "./recap-editor";
import "@/components/recaps/recaps.css";

export const metadata = { title: "Your builder recaps | Zynd", robots: { index: false, follow: false } };

export default async function RecapsPage({ searchParams }: { searchParams: Promise<{ id?: string }> }) {
  const client = await createClient();
  const { data: { session } } = await client.auth.getSession();
  if (!session?.access_token) redirect("/auth?next=/home/recaps");
  let initial: RecapHome;
  try {
    initial = await ownerRequest<RecapHome>("mine/recaps", session.access_token);
  } catch (error) {
    return <main className="recap-page"><div className="recap-shell recap-panel"><h1>Your recaps are unavailable</h1>
      <p>{error instanceof Error ? error.message : "Please try again shortly."}</p>
      <Link href="/home/recaps">Try again</Link> · <Link href="/home">Back home</Link></div></main>;
  }
  const { id } = await searchParams;
  return <RecapEditor initial={initial} token={session.access_token} initialId={id} />;
}
