import type { Metadata } from "next";
import { AskBox } from "@/components/dear/ask-box";
import { Footer, TopBar } from "@/components/dear/ui";

export const metadata: Metadata = { title: "Find someone" };

type Props = { searchParams: Promise<{ q?: string | string[] }> };

/**
 * One search page (the review found three: /directory, /search and /find,
 * each with a different look). Any other entry point should link here with ?q=.
 */
export default async function FindPage({ searchParams }: Props) {
  const raw = (await searchParams).q;
  const q = Array.isArray(raw) ? raw[0] : raw ?? "";
  return (
    <div className="shell narrow">
      <TopBar current="/dear/find" />
      <header className="stack">
        <h1 className="display" style={{ fontSize: "clamp(40px, 6vw, 64px)" }}>
          Find someone.
        </h1>
        <p className="lede">Ask in plain words. You see why each person matched, and how recently they said it.</p>
      </header>
      <AskBox initial={q} autoRun />
      <Footer />
    </div>
  );
}
