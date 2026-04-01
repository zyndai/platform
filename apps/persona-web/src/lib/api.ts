/**
 * API helper — wraps fetch calls to the Python backend.
 * Automatically attaches the Supabase JWT as a Bearer token.
 */
import { getSupabase } from "./supabase";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getAuthHeaders(): Promise<Record<string, string>> {
  const sb = getSupabase();
  const {
    data: { session },
  } = await sb.auth.getSession();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (session?.access_token) {
    headers["Authorization"] = `Bearer ${session.access_token}`;
  }
  return headers;
}

export async function apiGet<T = unknown>(path: string): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}${path}`, { headers });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function apiPost<T = unknown>(
  path: string,
  body: unknown
): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function apiDelete<T = unknown>(path: string): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
