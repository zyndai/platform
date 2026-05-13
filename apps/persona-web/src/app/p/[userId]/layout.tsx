import type { Metadata } from "next";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface PublicPersona {
  name?: string;
  description?: string;
  avatar_url?: string | null;
  title?: string | null;
  organization?: string | null;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ userId: string }>;
}): Promise<Metadata> {
  const { userId } = await params;
  let persona: PublicPersona | null = null;
  try {
    const res = await fetch(`${API}/api/persona/${userId}/public`, {
      // Keep these fresh-ish — public page changes when the user edits
      // their profile. 60s is plenty for share-time previews and still
      // saves us re-fetching on every crawler hit.
      next: { revalidate: 60 },
    });
    if (res.ok) persona = (await res.json()) as PublicPersona;
  } catch {
    /* fall through to defaults */
  }

  const name = persona?.name?.trim() || "ZyndAI Agent";
  const subtitle = [persona?.title, persona?.organization].filter(Boolean).join(" · ");
  const description =
    persona?.description?.trim() ||
    (subtitle ? `${name} — ${subtitle}. Reach them through their agent on ZyndAI.` : "Reach them through their agent on ZyndAI.");
  const title = `${name} · ZyndAI`;
  const images = persona?.avatar_url ? [{ url: persona.avatar_url, alt: name }] : undefined;

  return {
    title,
    description,
    openGraph: {
      title,
      description,
      type: "profile",
      images,
    },
    twitter: {
      card: images ? "summary_large_image" : "summary",
      title,
      description,
      images: images?.map((i) => i.url),
    },
  };
}

export default function PublicPersonaLayout({ children }: { children: React.ReactNode }) {
  return children;
}
