import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { fetchFeed, parseFilter, type FeedPage } from "@/lib/feed";
import { DiscoverShell } from "@/components/discover/discover-shell";
import { FeedClient } from "./feed-client";
import "./feed.css";

export const metadata = {
  title: "Feed · Zynd Cards",
  robots: { index: false, follow: false },
};
export const dynamic = "force-dynamic";

export default async function FeedPage({ searchParams }: { searchParams: Promise<{ filter?: string | string[] }> }) {
  const filter = parseFilter((await searchParams)?.filter);
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session?.access_token) redirect("/auth?next=/feed");

  // Request-scoped clock so server and client render the same relative times.
  // eslint-disable-next-line react-hooks/purity -- RSC request-scoped clock
  const nowMs = Date.now();
  let initial: FeedPage;
  try {
    initial = await fetchFeed(session.access_token, { filter });
  } catch {
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
      <FeedClient key={filter} initial={initial} filter={filter} token={session.access_token} nowMs={nowMs} />
    </DiscoverShell>
  );
}
