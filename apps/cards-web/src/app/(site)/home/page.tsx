import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import {
  ownerHomeEnabled,
  ownerRequest,
  type OwnerStatus,
} from "@/lib/owner-home";
import { OwnerHome } from "./owner-home";

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
      <main style={{ padding: 48 }}>
        <h1>Your home is temporarily unavailable</h1>
        <p>Please try again shortly.</p>
        <Link href="/home">Try again</Link>
      </main>
    );
  }
  if (!data)
    return (
      <main style={{ padding: 48 }}>
        <h1>Welcome home</h1>
        <p>Create your card to start seeing how people find you.</p>
        <Link href="/create">Create your card →</Link>
      </main>
    );
  return <OwnerHome initial={data} token={session.access_token} />;
}
