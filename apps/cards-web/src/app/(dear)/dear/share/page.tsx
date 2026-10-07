import type { Metadata } from "next";
import { Footer, TopBar } from "@/components/dear/ui";
import { getIntros, getMyLetter, getPencilled } from "@/lib/dear/repo";
import { ShareClient } from "./share-client";

export const metadata: Metadata = { title: "Share" };

export default async function SharePage() {
  const [letter, pencilled, intros] = await Promise.all([getMyLetter(), getPencilled(), getIntros()]);
  return (
    <div className="shell narrow">
      <TopBar owner current="/dear/share" inbox={pencilled.length + intros.filter((i) => i.status === "waiting").length} />
      <ShareClient letter={letter} />
      <Footer />
    </div>
  );
}
