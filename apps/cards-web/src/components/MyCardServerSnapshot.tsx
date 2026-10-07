import { cache } from "react";
import { createClient } from "@/lib/supabase/server";
import { lookupMyCardHandle } from "@/lib/cards";
import { MyCardProvider, type MyCardSnapshot } from "@/hooks/useMyCard";

/**
 * Resolves the signed-in visitor's card on the server and seeds the client
 * MyCardProvider, so "My card" / "My profile" links paint on first render
 * instead of appearing after hydration + a /cards/mine round-trip.
 */
const computeSnapshot = cache(async (): Promise<MyCardSnapshot | null> => {
  try {
    const supabase = await createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) return null;
    const lookup = await lookupMyCardHandle(session.access_token);
    return {
      authenticated: true,
      handle: lookup.handle,
      card: lookup.card,
    };
  } catch {
    return null;
  }
});

export async function MyCardServerSnapshot({
  children,
}: {
  children: React.ReactNode;
}) {
  const initial = await computeSnapshot();
  return <MyCardProvider initial={initial}>{children}</MyCardProvider>;
}