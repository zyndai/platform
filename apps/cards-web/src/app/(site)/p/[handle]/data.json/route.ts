import { fetchCardByHandle, cardCanonicalUrl } from "@/lib/cards";

export const revalidate = 60;

interface Params {
  params: Promise<{ handle: string }>;
}

export async function GET(_req: Request, { params }: Params) {
  const { handle } = await params;
  const card = await fetchCardByHandle(handle);

  if (!card) {
    return new Response(JSON.stringify({ error: "not found" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }

  // S03: unclaimed cards stay quiet to agents — a minimal marker, no facts.
  if (card.claimed === false) {
    return new Response(
      JSON.stringify({ claimed: false, error: "unclaimed — this card's owner has not published it for agents" }, null, 2),
      {
        status: 410,
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": "public, s-maxage=300, stale-while-revalidate=600",
          "Access-Control-Allow-Origin": "*",
        },
      },
    );
  }

  const { identity } = card;
  const canonical = cardCanonicalUrl(card);

  const sameAs = Object.values(identity.links)
    .filter((v): v is string => Boolean(v))
    .filter((v) => /^https?:\/\//.test(v));

  const image = /^https?:\/\//.test(identity.avatar_url || "") ? identity.avatar_url : undefined;

  const knowsAbout = card.skills.map((s) => s.name).filter(Boolean);
  const credentials = card.skills
    .filter((s) => s.name && s.level)
    .map((s) => ({
      "@type": "EducationalOccupationalCredential",
      name: s.name,
      competencyRequired: s.level,
    }));

  const currentJobs = (card.work_experience ?? [])
    .filter((j) => /^(present|current|now)$/i.test((j.end_date || "").trim()) && (j.title || j.company))
    .map((j) => ({
      "@type": "Organization",
      name: j.company || j.title,
      ...(j.title && j.company ? { department: { "@type": "Organization", name: j.title } } : {}),
    }));

  const entity = {
    "@context": "https://schema.org",
    "@type": "Person",
    "@id": canonical,
    name: identity.name,
    url: canonical,
    description: card.summary || identity.headline,
    ...(image ? { image } : {}),
    ...(identity.headline ? { jobTitle: identity.headline } : {}),
    ...(identity.location ? { address: { "@type": "PostalAddress", addressLocality: identity.location } } : {}),
    ...(sameAs.length ? { sameAs } : {}),
    ...(knowsAbout.length ? { knowsAbout } : {}),
    ...(credentials.length ? { hasCredential: credentials } : {}),
    ...(currentJobs.length ? { worksFor: currentJobs } : {}),
    // Zynd-specific extensions
    "zynd:handle": handle,
    "zynd:card_id": card.id,
    ...(card.citation_snippet ? { "zynd:citation": card.citation_snippet } : {}),
    ...(card.searchable_facts?.length ? { "zynd:facts": card.searchable_facts } : {}),
    ...(card.updated_at ? { "zynd:verified_at": card.updated_at } : {}),
  };

  return new Response(JSON.stringify(entity, null, 2), {
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "public, s-maxage=60, stale-while-revalidate=300",
      "Access-Control-Allow-Origin": "*",
    },
  });
}
