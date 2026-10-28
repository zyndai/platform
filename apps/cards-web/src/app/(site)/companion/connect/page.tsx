import { redirect } from "next/navigation";

import { Navbar } from "@/components/Navbar";
import { getMyCard } from "@/lib/cards";
import { COMPANION_STATE } from "@/lib/companion";
import { createClient } from "@/lib/supabase/server";
import { ConnectClient } from "./connect-client";

export const dynamic = "force-dynamic";
export const metadata = { title: "Connect Zynd Companion · Zynd", robots: { index: false, follow: false } };

/** Where Zynd Companion pairs with a signed-in account. Signed out, it sends the person to sign in
 *  and back; the extension never sees a password or the website session, only the token minted here. */
export default async function ConnectPage({ searchParams }: { searchParams: Promise<{ state?: string }> }) {
  const raw = (await searchParams).state ?? "";
  const state = COMPANION_STATE.test(raw) ? raw : "";
  const { data: { session } } = await (await createClient()).auth.getSession();
  if (!session?.access_token) {
    redirect(`/auth?next=${encodeURIComponent(`/companion/connect${state ? `?state=${state}` : ""}`)}`);
  }
  const mine = await getMyCard(session.access_token);
  const account = mine
    ? { name: mine.card.identity.name, handle: mine.handle, headline: mine.card.identity.headline }
    : null;
  return (
    <>
      <Navbar />
      <ConnectClient state={state} token={session.access_token} account={account} exploring={mine?.card.exploring ?? []} />
    </>
  );
}
