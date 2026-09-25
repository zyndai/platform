import Link from "next/link";
import { Button } from "@/components/ui";
import { PersonaCardClient } from "./PersonaCardClient";
import type { PublicPersona } from "./utils";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface PageProps {
  params: Promise<{ userId: string }>;
}

async function fetchPersona(userId: string): Promise<PublicPersona | null> {
  try {
    const res = await fetch(`${API}/api/persona/${userId}/public`, {
      next: { revalidate: 60 },
    });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(await res.text());
    return (await res.json()) as PublicPersona;
  } catch {
    return null;
  }
}

export default async function PublicPersonaPage({ params }: PageProps) {
  const { userId } = await params;
  const persona = await fetchPersona(userId);

  if (!persona) {
    return (
      <PublicShell>
        <div className="public-empty-card">
          <h1>No card here.</h1>
          <p>The link is stale, or this persona was retired.</p>
          <Link href="/" style={{ textDecoration: "none" }}>
            <Button>Claim your ZyndAI agent</Button>
          </Link>
        </div>
      </PublicShell>
    );
  }

  return (
    <PublicShell>
      <PersonaCardClient persona={persona} userId={userId} />
    </PublicShell>
  );
}

function PublicShell({ children }: { children: React.ReactNode }) {
  return <div className="public-card-shell">{children}</div>;
}
