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
  notification_prefs: { weekly_digest: boolean; email_nudges: boolean; morning_digest?: boolean };
  /** IANA zone the morning digest is timed to; null until the owner has opened /home on a build that records it. */
  timezone?: string | null;
  duplicates: { id: string; handle: string; name: string; status: string }[];
  unclaimed_duplicates?: { handle: string; name: string }[];
  possible_duplicates?: { handle: string; name: string; matched_socials: string[]; mergeable: false }[];
  nudges: { id: string; kind: string; title: string; href: string }[];
  /** People to meet (cards-api services/suggestions.py); absent on older APIs. */
  suggestions?: { people: SuggestedPerson[]; outside: OutsidePerson[] };
}

/** A claimed Card suggested to the owner: someone who fits who they want to meet. */
export interface SuggestedPerson {
  handle: string;
  name: string;
  headline: string;
  location: string;
  avatar_url: string;
  url: string;
  /** They also want to meet someone like the owner. */
  two_way: boolean;
  /** At most three specific reasons, most telling first. */
  why: string[];
}

/** Someone not on Zynd yet (LinkedIn), shown when there are too few Zynd suggestions. */
export interface OutsidePerson {
  name: string;
  title: string;
  company: string;
  linkedin_url: string;
  /** The owner's assistant can invite them to claim a card (A2). */
  invitable?: boolean;
}

export type SuggestionFeedback = "hide" | "not_relevant";

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
