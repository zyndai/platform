import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PageViewer } from "./PageViewer";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface PublicPage {
  slug: string;
  url: string;
  title: string;
  format: "html" | "markdown";
  content: string;
  created_at: string | null;
}

interface PageProps {
  params: Promise<{ slug: string }>;
}

async function fetchPage(slug: string): Promise<PublicPage | null> {
  try {
    const res = await fetch(`${API}/api/pages/public/${slug}`, {
      // Public pages are mostly static once published; cache for a short
      // window to avoid hitting the backend on every share-link click.
      next: { revalidate: 60 },
    });
    if (!res.ok) return null;
    return (await res.json()) as PublicPage;
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const page = await fetchPage(slug);

  if (!page) {
    return { title: "Page not found" };
  }

  const description =
    page.format === "markdown"
      ? page.content.slice(0, 160).replace(/\n/g, " ")
      : "Shared page";

  return {
    title: page.title,
    description,
    openGraph: {
      title: page.title,
      description,
      type: "article",
      url: page.url,
    },
  };
}

export default async function PublishedPage({ params }: PageProps) {
  const { slug } = await params;
  const page = await fetchPage(slug);

  if (!page) {
    notFound();
  }

  return (
    <main className="published-page-shell">
      <PageViewer page={page} />
    </main>
  );
}
