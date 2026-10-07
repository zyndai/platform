import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { Footer, TopBar } from "@/components/dear/ui";
import { getLetter } from "@/lib/dear/repo";
import { ClaimClient } from "./claim-client";

export const metadata: Metadata = { title: "Is this you?" };

type Props = { params: Promise<{ handle: string }> };

export default async function ClaimPage({ params }: Props) {
  const { handle } = await params;
  const letter = await getLetter(handle);
  if (!letter) notFound();
  // A letter someone has already written cannot be claimed by anyone else.
  if (letter.claimed) redirect(`/dear/l/${handle}`);
  return (
    <div className="shell narrow">
      <TopBar />
      <ClaimClient letter={letter} />
      <Footer />
    </div>
  );
}
