export interface RecapHighlight {
  id: string;
  kind: "shipped" | "learned" | "exploring" | "github" | "repository" | "release" | "pull_request";
  title: string;
  url: string;
  date?: string;
  count?: number;
  source: string;
}

export interface Recap {
  id: string;
  period: string;
  handle: string;
  snapshot: {
    name: string;
    label: string;
    timezone: string;
    generated_at: string;
    in_progress: boolean;
    github_available: boolean;
    _caption_draft?: { caption: string; source: "llm" | "template" };
    github_activity?: {
      repositories?: "complete" | "partial" | "unavailable" | "not_connected";
      truncated: boolean;
    };
    history_note: string;
    highlights: RecapHighlight[];
  };
  caption: string;
  published_at: string | null;
  selected_ids?: string[];
  can_publish?: boolean;
}

export interface RecapHome {
  handle: string;
  recaps: Recap[];
  projects: { name: string; url: string }[];
  periods: string[];
}

export function recapPath(recap: Pick<Recap, "handle" | "id">): string {
  return `/p/${encodeURIComponent(recap.handle)}/recaps/${encodeURIComponent(recap.id)}`;
}

export function selectedHighlights(recap: Recap): RecapHighlight[] {
  const selected = recap.selected_ids && new Set(recap.selected_ids);
  return recap.snapshot.highlights.filter((h) => !selected || selected.has(h.id));
}

export function highlightLabel(highlight: RecapHighlight): string {
  const verbs = { repository: "New public repository", shipped: "Shipped", learned: "Learned", exploring: "Explored", release: "Released", pull_request: "Merged PR" };
  return highlight.kind === "github" ? `${highlight.count ?? 0} GitHub contributions` : `${verbs[highlight.kind]} ${highlight.title}`;
}

export function generatedCaption(recap: Recap): string {
  const highlights = selectedHighlights(recap);
  const named = (items: RecapHighlight[]) => items.slice(0, 2).map((h) => h.title).join(" and ") + (items.length > 2 ? ` and ${items.length - 2} more` : "");
  const repos = highlights.filter((h) => h.kind === "repository");
  const shipped = highlights.filter((h) => h.kind === "shipped");
  const learned = highlights.filter((h) => h.kind === "learned");
  const contributions = highlights.find((h) => h.kind === "github");
  const parts: string[] = [];
  if (repos.length) parts.push(`created ${repos.length} new public ${repos.length === 1 ? "repository" : "repositories"} (${named(repos)})`);
  if (contributions) parts.push(`made ${contributions.count} GitHub contributions`);
  if (shipped.length) parts.push(`shipped ${named(shipped)}`);
  if (learned.length) parts.push(`learned ${named(learned)}`);
  const period = `${recap.snapshot.label}${recap.snapshot.in_progress ? " so far" : ""}`;
  if (!parts.length) return `My ${period} on Zynd: no highlights recorded yet.`;
  const actions = parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}`;
  return `Hi connections, in ${period}, I ${actions}. Looking forward to sharing what comes next.`.slice(0, 2000);
}

export function recapStats(highlights: RecapHighlight[]): { value: string; label: string }[] {
  const stats: { value: string; label: string }[] = [];
  const shipped = highlights.filter((h) => h.kind === "shipped").length;
  const learned = highlights.filter((h) => h.kind === "learned").length;
  const exploring = highlights.filter((h) => h.kind === "exploring").length;
  const repos = highlights.filter((h) => h.kind === "repository").length;
  const github = highlights.find((h) => h.kind === "github");
  if (shipped) stats.push({ value: String(shipped), label: shipped === 1 ? "project shipped" : "projects shipped" });
  if (repos) stats.push({ value: String(repos), label: repos === 1 ? "new public repository" : "new public repositories" });
  if (github) stats.push({ value: String(github.count ?? 0), label: "GitHub contributions" });
  if (learned) stats.push({ value: String(learned), label: learned === 1 ? "learning milestone" : "learning milestones" });
  if (exploring) stats.push({ value: String(exploring), label: exploring === 1 ? "new exploration" : "new explorations" });
  return stats;
}

export const recapOrigin = (process.env.NEXT_PUBLIC_SITE_URL || "https://cards.zynd.ai").replace(/\/$/, "");

export async function fetchPublicRecap(handle: string, id: string): Promise<Recap | null> {
  if (!/^[\da-f-]{36}$/i.test(id)) return null;
  const api = (process.env.NEXT_PUBLIC_API_URL || "https://api.zynd.ai").replace(/\/$/, "");
  const response = await fetch(`${api}/cards/by-handle/${encodeURIComponent(handle)}/recaps/${encodeURIComponent(id)}`, { cache: "no-store" });
  if (response.status === 404 || response.status === 422) return null;
  if (!response.ok) throw new Error("Recap temporarily unavailable");
  return response.json();
}
