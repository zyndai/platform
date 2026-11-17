export interface RecapHighlight {
  id: string;
  kind: "shipped" | "learned" | "exploring" | "github" | "release" | "pull_request";
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
    github_activity?: {
      releases: "complete" | "partial" | "unavailable" | "not_connected";
      pull_requests: "complete" | "partial" | "unavailable" | "not_connected";
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
  const verbs = { shipped: "Shipped", learned: "Learned", exploring: "Explored", release: "Released", pull_request: "Merged PR" };
  return highlight.kind === "github" ? `${highlight.count ?? 0} GitHub contributions` : `${verbs[highlight.kind]} ${highlight.title}`;
}

export function generatedCaption(recap: Recap): string {
  const highlights = selectedHighlights(recap);
  const shipped = highlights.filter((h) => h.kind === "shipped").length;
  const lines = [`My ${recap.snapshot.label} on Zynd${recap.snapshot.in_progress ? " (so far)" : ""}`];
  if (shipped) lines.push(`Shipped ${shipped} project${shipped === 1 ? "" : "s"}.`);
  for (const h of highlights) {
    if (h.kind === "github") lines.push(`${h.count} GitHub contributions.`);
    else if (h.kind === "learned" || h.kind === "exploring") lines.push(`${h.kind === "learned" ? "Learned" : "Explored"} ${h.title}.`);
    else if (h.kind === "release" || h.kind === "pull_request") lines.push(`${highlightLabel(h)}.`);
  }
  return lines.join("\n").slice(0, 2000);
}

export function recapStats(highlights: RecapHighlight[]): { value: string; label: string }[] {
  const stats: { value: string; label: string }[] = [];
  const shipped = highlights.filter((h) => h.kind === "shipped").length;
  const learned = highlights.filter((h) => h.kind === "learned").length;
  const exploring = highlights.filter((h) => h.kind === "exploring").length;
  const releases = highlights.filter((h) => h.kind === "release").length;
  const prs = highlights.filter((h) => h.kind === "pull_request").length;
  const github = highlights.find((h) => h.kind === "github");
  if (shipped) stats.push({ value: String(shipped), label: shipped === 1 ? "project shipped" : "projects shipped" });
  if (releases) stats.push({ value: String(releases), label: releases === 1 ? "release" : "releases" });
  if (prs) stats.push({ value: String(prs), label: prs === 1 ? "merged PR" : "merged PRs" });
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
