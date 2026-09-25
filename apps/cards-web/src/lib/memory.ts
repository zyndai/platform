import { CARDS_API } from "@/lib/cards";
import type { MemoryFact } from "@/lib/memory-facts";

export const MEMORY_API = process.env.NEXT_PUBLIC_ZYND_API_URL || "https://api.zynd.ai";

export type MemoryProvider = "mem0" | "zep" | "letta" | "supermemory";

export async function exchangeZyndToken(supabaseToken: string): Promise<string> {
  const res = await fetch(`${MEMORY_API}/token/exchange`, {
    method: "POST",
    headers: { Authorization: `Bearer ${supabaseToken}` },
  });
  if (!res.ok) {
    throw new Error(`Could not connect to ZYND memory (${res.status})`);
  }
  const data = (await res.json()) as { token?: string };
  if (!data.token) {
    throw new Error("ZYND did not return a session");
  }
  return data.token;
}

export async function previewProviderMemory(opts: {
  zyndToken: string;
  apiKey: string;
  userId?: string;
}): Promise<{ provider: MemoryProvider | string; facts: MemoryFact[] }> {
  const body: Record<string, string> = { api_key: opts.apiKey };
  const uid = opts.userId?.trim();
  if (uid) body.user_id = uid;
  const res = await fetch(`${MEMORY_API}/me/providers/preview`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${opts.zyndToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as {
    facts?: MemoryFact[];
    provider?: string;
    detail?: string;
  };
  if (res.status === 401) {
    throw new Error(data.detail || "That API key was rejected. Check it and try again.");
  }
  if (res.status === 404) {
    throw new Error("This ZYND API does not have memory import yet. Point the dashboard at a memory-layer that has /me/providers/preview.");
  }
  if (!res.ok) {
    throw new Error(data.detail || `Could not read that memory provider (${res.status})`);
  }
  return {
    provider: data.provider || "unknown",
    facts: Array.isArray(data.facts) ? data.facts : [],
  };
}

export async function declareMemoryFacts(opts: {
  zyndToken: string;
  facts: MemoryFact[];
}): Promise<{ declared: number; skipped: number }> {
  const declarations = opts.facts
    .filter((fact) => fact.predicate && fact.object.trim())
    .slice(0, 50)
    .map((fact) => ({ predicate: fact.predicate, value: fact.object.trim() }));
  if (declarations.length === 0) {
    return { declared: 0, skipped: 0 };
  }
  const res = await fetch(`${MEMORY_API}/me/findability/declare-batch`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${opts.zyndToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ declarations }),
  });
  if (!res.ok) {
    throw new Error(`Could not save facts (${res.status})`);
  }
  const data = (await res.json()) as {
    declared?: unknown[];
    skipped?: unknown[];
  };
  return {
    declared: Array.isArray(data.declared) ? data.declared.length : 0,
    skipped: Array.isArray(data.skipped) ? data.skipped.length : 0,
  };
}

export async function refreshCardMemory(opts: {
  supabaseToken: string;
  handle: string;
}): Promise<MemoryFact[] | null> {
  const res = await fetch(
    `${CARDS_API}/cards/by-handle/${encodeURIComponent(opts.handle)}/refresh-memory`,
    { method: "POST", headers: { Authorization: `Bearer ${opts.supabaseToken}` } },
  );
  if (!res.ok) {
    throw new Error(`Could not update the profile tile (${res.status})`);
  }
  const data = (await res.json()) as { zynd_memory?: MemoryFact[] | null };
  return data.zynd_memory ?? [];
}
