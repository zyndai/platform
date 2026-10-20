import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { NetworkClient } from "./network-client";
import { NetworkV2 } from "./network-v2";

export const dynamic = "force-dynamic";
export const metadata = {
  title: "Your network · Zynd Cards",
  robots: { index: false, follow: false },
};

export default async function NetworkPage({ searchParams }: { searchParams: Promise<{ v2?: string }> }) {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session?.access_token || !session.user) {
    redirect("/auth?next=/network");
  }
  const params = await searchParams;
  const v2 = process.env.FEATURE_NETWORK_V2 === "true" || params?.v2 === "1";
  return v2
    ? <NetworkV2 token={session.access_token} userId={session.user.id} />
    : <NetworkClient token={session.access_token} userId={session.user.id} />;
}
