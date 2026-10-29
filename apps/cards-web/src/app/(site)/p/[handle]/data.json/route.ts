import {
  fetchCardByHandle,
  fetchCardView,
  cardIsClaimed,
  cardCanonicalUrl,
  featureS06CardView,
  type CardFact,
} from "@/lib/cards";
import { logAgentFetch } from "@/lib/track";
import { ownerHomeEnabled } from "@/lib/owner-home";
import { cleanTopic, publicTopics } from "@/lib/profile-quality";

export const revalidate = 60;

interface Params {
  params: Promise<{ handle: string }>;
}

function liveFactsFromMemory(raw: Array<Record<string, unknown>> | null | undefined): CardFact[] {
  const HALF: Record<string, number> = {
    is_seeking: 7,
    is_working_on: 14,
    is_building: 60,
  };
  const now = Date.now();
  const out: CardFact[] = [];
  for (const f of raw || []) {
    if (!f) continue;
    const text = String(f.object || f.value || "").trim();
    const type = String(f.predicate || f.type || "").trim();
    if (!text) continue;
    if (["has_skill", "has_expertise_in", "is_learning"].includes(type) && !cleanTopic(text)) continue;
    const approved = typeof f.approved_at === "string" ? f.approved_at : null;
    let expires_at: string | null = null;
    const days = HALF[type];
    if (days && approved) {
      const t = Date.parse(approved);
      if (!Number.isNaN(t)) {
        expires_at = new Date(t + days * 86400000).toISOString();
        if (Date.parse(expires_at) <= now) continue;
      }
    }
    out.push({
      text,
      type,
      source: String(f.source || ""),
      approved_at: approved,
      expires_at,
      confidence: typeof f.confidence === "number" ? f.confidence : null,
    });
  }
  return out;
}

export async function GET(req: Request, { params }: Params) {
  const { handle } = await params;
  logAgentFetch("data.json", req.headers.get("user-agent"), handle);
  const card = await fetchCardByHandle(handle);

  if (card?.handle && card.handle !== handle) {
    const target = new URL(req.url);
    target.pathname = `/p/${encodeURIComponent(card.handle)}/data.json`;
    return Response.redirect(target, 301);
  }

  if (!card) {
    return new Response(JSON.stringify({ error: "not found" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }

  // S03: unclaimed cards stay quiet to agents — a minimal marker, no facts.
  if (!cardIsClaimed(card)) {
    return new Response(
      JSON.stringify({ claimed: false, error: "unclaimed — this card's owner has not published it for agents" }, null, 2),
      {
        status: 410,
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": ownerHomeEnabled ? "no-store" : "public, s-maxage=300, stale-while-revalidate=600",
          "Access-Control-Allow-Origin": "*",
        },
      },
    );
  }

  const view = featureS06CardView() ? await fetchCardView(handle) : null;
  const identity = view?.identity ?? card.identity;
  const canonical = view?.cite_as || cardCanonicalUrl(card);

  const sameAs = Object.values(identity.links || {})
    .filter((v): v is string => Boolean(v))
    .filter((v) => /^https?:\/\//.test(v));

  const image = /^https?:\/\//.test(identity.avatar_url || "") ? identity.avatar_url : undefined;

  const skills = view?.skills ?? card.skills;
  const credentials = skills
    .filter((s) => s.name && s.level)
    .map((s) => ({
      "@type": "EducationalOccupationalCredential",
      name: s.name,
      competencyRequired: s.level,
    }));

  const facts: CardFact[] = view
    ? view.facts.filter((f) => f && f.text)
    : liveFactsFromMemory(card.zynd_memory as Array<Record<string, unknown>> | null);

  const knowsAbout = publicTopics(skills, facts);

  const affiliationOrgs = facts
    .filter((f) => f.type === "is_affiliated_with" && f.text)
    .map((f) => ({ "@type": "Organization", name: f.text }));

  const currentJobs = (card.work_experience ?? [])
    .filter((j) => /^(present|current|now)$/i.test((j.end_date || "").trim()) && (j.title || j.company))
    .map((j) => ({
      "@type": "Organization",
      name: j.company || j.title,
      ...(j.title && j.company ? { department: { "@type": "Organization", name: j.title } } : {}),
    }));

  const worksFor = [...currentJobs, ...affiliationOrgs.filter((o) => !currentJobs.some((j) => j.name === o.name))];
  const beacon = view?.beacon ?? card.beacon;
  const activeBeacon = beacon && Date.parse(beacon.created_at) <= Date.now() && Date.parse(beacon.expires_at) > Date.now() ? beacon : null;

  const jobFromFacts = facts.find((f) => f.type === "is_affiliated_with")?.text;
  const jobTitle = identity.headline || jobFromFacts || undefined;

  const entity = {
    "@context": "https://schema.org",
    "@type": "Person",
    "@id": canonical,
    name: identity.name,
    url: canonical,
    description: (view?.summary ?? card.summary) || identity.headline,
    ...(image ? { image } : {}),
    ...(jobTitle ? { jobTitle } : {}),
    ...(identity.location ? { address: { "@type": "PostalAddress", addressLocality: identity.location } } : {}),
    ...(sameAs.length ? { sameAs } : {}),
    ...(knowsAbout.length ? { knowsAbout } : {}),
    ...(credentials.length ? { hasCredential: credentials } : {}),
    ...(worksFor.length ? { worksFor } : {}),
    "zynd:handle": handle,
    "zynd:card_id": card.id,
    ...(activeBeacon ? { "zynd:beacon": activeBeacon } : {}),
    ...(card.helped?.count ? { "zynd:helped": card.helped } : {}),
    ...(card.citation_snippet ? { "zynd:citation": card.citation_snippet } : {}),
    ...(facts.length
      ? {
          "zynd:facts": facts.map((f) => ({
            text: f.text,
            type: f.type,
            source: f.source || "",
            approved_at: f.approved_at || null,
            expires_at: f.expires_at || null,
            ...(f.confidence != null ? { confidence: f.confidence } : {}),
          })),
        }
      : {}),
    "zynd:claimed": true,
    "zynd:cite_as": canonical,
    ...((view?.fresh_as_of || card.updated_at) ? { "zynd:verified_at": view?.fresh_as_of || card.updated_at } : {}),
  };

  return new Response(JSON.stringify(entity, null, 2), {
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": ownerHomeEnabled ? "no-store" : "public, s-maxage=60, stale-while-revalidate=300",
      "Access-Control-Allow-Origin": "*",
    },
  });
}
