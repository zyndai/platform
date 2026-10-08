import type { Metadata } from "next";
import Link from "next/link";
import { CARDS_API } from "@/lib/cards";

export const revalidate = 0;

interface SearchResult {
  handle: string;
  agent_id: string;
  name: string;
  headline: string;
  location: string;
  skills: string[];
  availability: string;
  experience_years: number | null;
  match_score: number;
  match_reasons: string[];
  url: string;
  claimed?: boolean;
}

interface AskResponse {
  numberOfItems: number;
  results: SearchResult[];
  clarification_hints?: string[];
  search_guidance?: { role_detected: string; attribute_importance: Record<string, string> };
  parsed_query?: Record<string, unknown>;
}

interface PageProps {
  searchParams: Promise<{ q?: string; limit?: string }>;
}

export async function generateMetadata({ searchParams }: PageProps): Promise<Metadata> {
  const { q } = await searchParams;
  return {
    title: q ? `Find: ${q} — Zynd` : "Find people — Zynd",
    description: q
      ? `Search results for "${q}" on Zynd — ranked profiles with skills, location, and availability.`
      : "Find people on Zynd by role, skills, location, and availability.",
    robots: { index: false, follow: false },
  };
}

async function searchPeople(q: string, limit: number): Promise<AskResponse | null> {
  try {
    // The website's own directory UI may include unclaimed cards (labelled).
    const url = `${CARDS_API}/ask?q=${encodeURIComponent(q)}&limit=${limit}&include_unclaimed=true`;
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

// This page sits on the dark site shell, so it owns a light canvas of its own.
// Every colour below is chosen for ≥4.5:1 contrast against that canvas.
const INK = "#1a1a1a";
const SUB = "#4b4b46";
const FAINT = "#6b6b64";
const LINK = "#1d4ed8";

export default async function FindPage({ searchParams }: PageProps) {
  const { q = "", limit: limitStr = "10" } = await searchParams;
  const limit = Math.min(Math.max(parseInt(limitStr, 10) || 10, 1), 50);

  const data = q ? await searchPeople(q, limit) : null;

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", minHeight: "100dvh", background: "#F7F6F2", color: INK }}>
      <div style={{ maxWidth: 800, margin: "0 auto", padding: "2rem 1.5rem 4rem" }}>
      <header style={{ marginBottom: "2rem" }}>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 700, marginBottom: "0.5rem", color: INK }}>
          Zynd — Find People
        </h1>
        <p style={{ color: SUB, fontSize: "0.95rem", marginBottom: "1.25rem" }}>
          Search Zynd&apos;s directory of people by role, skills, location, or availability.
          Append <code>?q=your query</code> to this URL or use the form below.
        </p>

        <form method="get" action="/find" style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <input
            name="q"
            type="text"
            defaultValue={q}
            placeholder="e.g. GTM engineer in Bangalore freelance"
            style={{ flex: 1, minWidth: 280, padding: "0.5rem 0.75rem", border: "1px solid #b9b7ae", borderRadius: 6, fontSize: "1rem", background: "#fff", color: INK }}
          />
          <button type="submit" style={{ padding: "0.5rem 1.25rem", background: "#0B0B0B", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer", fontSize: "1rem" }}>
            Search
          </button>
        </form>

        <p style={{ marginTop: "0.75rem", fontSize: "0.85rem", color: FAINT }}>
          API: <code>{CARDS_API}/ask?q={"{your query}"}</code> — returns schema.org JSON
        </p>
      </header>

      {q && !data && (
        <p style={{ color: "#b91c1c" }}>Search unavailable. Try again shortly.</p>
      )}

      {q && data && data.results.length === 0 && (
        <p style={{ color: SUB }}>
          No one matches that search.{" "}
          <Link href="/create" style={{ color: LINK }}>
            Create your card
          </Link>{" "}
          so people can find you.
        </p>
      )}

      {data && (
        <>
          {data.clarification_hints && data.clarification_hints.length > 0 && (
            <section style={{ background: "#fff", border: "1px solid #dedbd0", borderRadius: 8, padding: "1rem 1.25rem", marginBottom: "1.5rem" }}>
              <strong style={{ fontSize: "0.85rem", color: SUB, textTransform: "uppercase", letterSpacing: "0.04em" }}>To improve results, consider:</strong>
              <ul style={{ margin: "0.5rem 0 0 1.25rem", fontSize: "0.9rem", color: INK }}>
                {data.clarification_hints.map((h, i) => <li key={i}>{h}</li>)}
              </ul>
            </section>
          )}

          {data.search_guidance && (
            <section style={{ fontSize: "0.85rem", color: FAINT, marginBottom: "1rem" }}>
              <strong>Role detected:</strong> {data.search_guidance.role_detected} &nbsp;·&nbsp;
              <strong>Key attributes:</strong>{" "}
              {Object.entries(data.search_guidance.attribute_importance)
                .filter(([, v]) => v === "HIGH")
                .map(([k]) => k)
                .join(", ")}
            </section>
          )}

          <p style={{ fontSize: "0.9rem", color: SUB, marginBottom: "1.5rem" }}>
            {data.numberOfItems} result{data.numberOfItems !== 1 ? "s" : ""} for &ldquo;{q}&rdquo;
            {data.parsed_query && Object.keys(data.parsed_query).length > 0 && (
              <span> &nbsp;·&nbsp; parsed: {JSON.stringify(data.parsed_query)}</span>
            )}
          </p>

          <ol style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "1rem" }}>
            {data.results.map((r, i) => {
              const profileUrl = `/p/${r.handle || r.agent_id}`;
              return (
                <li key={r.handle || r.agent_id} style={{ border: "1px solid #dedbd0", borderRadius: 10, padding: "1rem 1.25rem", background: "#fff" }}>
                  <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "1rem" }}>
                    <div>
                      <span style={{ fontSize: "0.8rem", color: FAINT, marginRight: "0.5rem" }}>#{i + 1}</span>
                      <Link href={profileUrl} style={{ fontWeight: 700, fontSize: "1.05rem", color: INK, textDecoration: "none" }}>
                        {r.name}
                      </Link>
                      {r.claimed === false && (
                        <span style={{ marginLeft: "0.5rem", fontSize: "0.7rem", fontWeight: 700, color: "#92610a", background: "#f7e8c4", borderRadius: 999, padding: "0.1rem 0.5rem", verticalAlign: "middle" }}>
                          Unclaimed
                        </span>
                      )}
                      {r.headline && (
                        <p style={{ margin: "0.2rem 0 0", color: SUB, fontSize: "0.9rem" }}>{r.headline}</p>
                      )}
                    </div>
                    <span style={{ whiteSpace: "nowrap", fontSize: "0.8rem", color: "#3b3b37", background: "#eeede7", borderRadius: 4, padding: "0.2rem 0.5rem" }}>
                      {Math.round(r.match_score * 100)}% match
                    </span>
                  </div>

                  <div style={{ marginTop: "0.6rem", display: "flex", flexWrap: "wrap", gap: "0.4rem", fontSize: "0.82rem" }}>
                    {r.location && <span style={{ background: "#eeede7", borderRadius: 4, padding: "0.15rem 0.5rem", color: INK }}>📍 {r.location}</span>}
                    {r.availability && <span style={{ background: "#e3efe6", borderRadius: 4, padding: "0.15rem 0.5rem", color: "#14532d" }}>✅ {r.availability}</span>}
                    {r.skills.slice(0, 5).map((s) => (
                      <span key={s} style={{ background: "#e8ecf8", borderRadius: 4, padding: "0.15rem 0.5rem", color: "#23294d" }}>{s}</span>
                    ))}
                  </div>

                  {r.match_reasons.length > 0 && (
                    <p style={{ marginTop: "0.5rem", fontSize: "0.82rem", color: FAINT }}>
                      {r.match_reasons.join(" · ")}
                    </p>
                  )}

                  <Link href={profileUrl} style={{ display: "inline-block", marginTop: "0.6rem", fontSize: "0.85rem", color: LINK }}>
                    View profile →
                  </Link>
                </li>
              );
            })}
          </ol>
        </>
      )}

      {!q && (
        <section>
          <h2 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "0.75rem", color: INK }}>Example searches</h2>
          <ul style={{ listStyle: "none", padding: 0, display: "flex", flexDirection: "column", gap: "0.4rem" }}>
            {[
              "GTM engineer in Bangalore freelance",
              "blockchain developer open to work",
              "senior React engineer San Francisco",
              "ML engineer 5+ years",
              "product designer remote",
            ].map((ex) => (
              <li key={ex}>
                <Link href={`/find?q=${encodeURIComponent(ex)}`} style={{ color: LINK, fontSize: "0.9rem" }}>
                  {ex}
                </Link>
              </li>
            ))}
          </ul>

          <h2 style={{ fontSize: "1rem", fontWeight: 600, margin: "2rem 0 0.75rem", color: INK }}>Search dimensions</h2>
          <p style={{ fontSize: "0.9rem", color: SUB }}>
            Results improve significantly when the query includes: <strong>role</strong>, <strong>location</strong>,
            <strong> skills</strong>, <strong>availability</strong> (fulltime / freelance / open to work),
            <strong> industry</strong>, or <strong>experience level</strong>.
          </p>
        </section>
      )}
      </div>
    </main>
  );
}