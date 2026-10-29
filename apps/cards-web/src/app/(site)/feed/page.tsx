import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { fetchFeed, parseFilter, parseKind } from "@/lib/feed";
import { fetchLiveAsk } from "@/lib/asks";
import { DiscoverShell } from "@/components/discover/discover-shell";
import { FeedClient } from "./feed-client";
import "@/components/feed/feed.css";

export const metadata = {
  title: "Feed · Zynd Cards",
  robots: { index: false, follow: false },
};
export const dynamic = "force-dynamic";

export default async function FeedPage({
  searchParams,
}: {
  searchParams: Promise<{ filter?: string | string[]; kind?: string | string[] }>;
}) {
  const params = await searchParams;
  const filter = parseFilter(params?.filter);
  // A kind only narrows the asks.
  const kind = filter === "asks" ? parseKind(params?.kind) : null;
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session?.access_token) redirect("/auth?next=/feed");

  // Request-scoped clock so server and client render the same relative times.
  // eslint-disable-next-line react-hooks/purity -- RSC request-scoped clock
  const nowMs = Date.now();
  // The viewer's own live ask rides along with the feed (fetchLiveAsk never throws: without it the
  // feed still renders).
  const [page, live] = await Promise.allSettled([
    fetchFeed(session.access_token, { filter, kind }),
    fetchLiveAsk(session.access_token, nowMs),
  ]);
  if (page.status === "rejected") {
    return (
      <DiscoverShell active="feed">
        <div className="fd-page">
          <section className="fd-panel fd-fallback">
            <h1>Your feed is temporarily unavailable</h1>
            <p>Please try again shortly.</p>
            <Link className="fd-button" href={filter === "all" ? "/feed" : `/feed?filter=${filter}`}>Try again</Link>
          </section>
        </div>
      </DiscoverShell>
    );
  }
  return (
    <DiscoverShell active="feed">
      <FeedClient
        key={`${filter}:${kind ?? ""}`}
        initial={page.value}
        filter={filter}
        kind={kind}
        live={live.status === "fulfilled" ? live.value : null}
        token={session.access_token}
        nowMs={nowMs}
      />
    </DiscoverShell>
  );
}
