import type { Metadata } from "next";
import { Footer, TopBar } from "@/components/dear/ui";
import { getIntros, getMyLetter, getPencilled } from "@/lib/dear/repo";
import { LetterEditor } from "./letter-editor";

export const metadata: Metadata = { title: "Edit my letter" };

export default async function LetterPage() {
  const [letter, pencilled, intros] = await Promise.all([getMyLetter(), getPencilled(), getIntros()]);
  return (
    <div className="shell narrow">
      <TopBar owner current="/dear/letter" inbox={pencilled.length + intros.filter((i) => i.status === "waiting").length} />
      <LetterEditor letter={letter} />
      <Footer />
    </div>
  );
}
