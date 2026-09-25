import { cache } from "react";
import { cookies } from "next/headers";
import type { User } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/server";

export interface ServerAuth {
  user: User | null;
}

/**
 * SSR-side session lookup for the root layout, so the client doesn't flash
 * an unauthenticated state before hydration. Skips the Supabase round-trip
 * when there's no `sb-`-prefixed cookie at all.
 */
export const getServerAuth = cache(async (): Promise<ServerAuth> => {
  const cookieStore = await cookies();
  const hasAuthCookie = cookieStore.getAll().some((c) => c.name.startsWith("sb-"));
  if (!hasAuthCookie) return { user: null };

  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  return { user };
});
