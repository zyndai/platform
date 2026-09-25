/**
 * Supabase browser client — lazy singleton.
 *
 * Call getSupabase() from inside event handlers / useEffect only.
 * Never import a bare `supabase` constant — it would execute during
 * SSR where env vars may not be available.
 */
import { createClient, SupabaseClient } from "@supabase/supabase-js";

let _client: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient {
  if (_client) return _client;

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !key) {
    throw new Error(
      "Missing NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY. " +
      "Check your .env.local file."
    );
  }

  _client = createClient(url, key);
  return _client;
}
