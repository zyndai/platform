import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { NetworkClient } from "./network-client";

export const dynamic = "force-dynamic";
export const metadata = {
  title: "Your network · Zynd Cards",
  robots: { index: false, follow: false },
};

export default async function NetworkPage() {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session?.access_token || !session.user) {
    redirect("/auth?next=/network");
  }
  return <NetworkClient token={session.access_token} userId={session.user.id} />;
}
