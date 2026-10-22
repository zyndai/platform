import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { parseConnectionParam } from "@/lib/cards-network";
import { DiscoverShell } from "@/components/discover/discover-shell";
import { NetworkClient } from "./network-client";
import { NetworkV2 } from "./network-v2";

export const dynamic = "force-dynamic";
export const metadata = {
  title: "Your network · Zynd Cards",
  robots: { index: false, follow: false },
};

export default async function NetworkPage({ searchParams }: { searchParams: Promise<{ v2?: string; c?: string | string[] }> }) {
  const params = await searchParams;
  // `?c=<connection id>` opens that conversation (the profile page's Message button links here).
  // Anything that is not a UUID is dropped rather than carried into the sign-in return path.
  const connectionId = parseConnectionParam(params?.c);
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session?.access_token || !session.user) {
    redirect(`/auth?next=${encodeURIComponent(connectionId ? `/network?c=${connectionId}` : "/network")}`);
  }
  const v2 = process.env.FEATURE_NETWORK_V2 === "true" || params?.v2 === "1";
  return v2
    ? (
      <DiscoverShell active="network" app>
        <NetworkV2
          token={session.access_token}
          userId={session.user.id}
          initialConnectionId={connectionId}
          groupMemoryEnabled={process.env.FEATURE_GROUP_MEMORY === "true"}
          groupAgentRepliesEnabled={process.env.FEATURE_GROUP_AGENT_REPLIES !== "false"}
        />
      </DiscoverShell>
    )
    : <NetworkClient token={session.access_token} userId={session.user.id} />;
}
