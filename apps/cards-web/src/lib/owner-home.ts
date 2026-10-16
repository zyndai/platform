export const ownerHomeEnabled =
  (process.env.NEXT_PUBLIC_FEATURE_S10_HOME ?? "true") === "true";

export interface OwnerStatus {
  handle: string;
  card_id: string;
  name: string;
  visibility: "public" | "private";
  completeness: {
    score: number;
    actions: { section: string; title: string; href: string }[];
  };
  inbox_count: number | null;
  connection: {
    memory_connected: boolean | null;
    assistants_available: boolean;
  };
  sources: { platform: string; scraped_at: string; state: string }[];
  activity: {
    available: boolean;
    views: number | null;
    agent_hits: number | null;
    intro_requests: number | null;
    queries: { query: string; count?: number }[];
    query_capture_available: boolean;
    chat_topics?: { category: string; count: number }[];
    chat_questions?: { question: string; category: string; asked_at: string | null; truncated: boolean }[];
  };
  visitors?: { available: boolean; items: { name: string; handle?: string | null; visited_at: string; visits: number }[] };
  notification_prefs: { weekly_digest: boolean; email_nudges: boolean };
  duplicates: { id: string; handle: string; name: string; status: string }[];
  unclaimed_duplicates?: { handle: string; name: string }[];
  nudges: { id: string; kind: string; title: string; href: string }[];
}

export async function ownerRequest<T>(
  path: string,
  token: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const api = (
    process.env.NEXT_PUBLIC_API_URL || "https://api.zynd.ai"
  ).replace(/\/$/, "");
  const res = await fetch(`${api}/cards/${path}`, {
    method,
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!res.ok) {
    let message = "Could not save. Please try again.";
    try {
      message = (await res.json()).detail || message;
    } catch {
      /* Keep useful fallback. */
    }
    throw new Error(message);
  }
  return res.status === 204 ? (null as T) : (res.json() as Promise<T>);
}
