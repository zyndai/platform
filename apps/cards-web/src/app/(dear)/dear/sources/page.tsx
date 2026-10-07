import type { Metadata } from "next";
import { Footer, TopBar } from "@/components/dear/ui";
import { getIntros, getPencilled, getSources } from "@/lib/dear/repo";
import { SourcesClient } from "./sources-client";

export const metadata: Metadata = { title: "Sources" };

export default async function SourcesPage() {
  const [sources, pencilled, intros] = await Promise.all([getSources(), getPencilled(), getIntros()]);
  return (
    <div className="shell narrow">
      <TopBar owner current="/dear/sources" inbox={pencilled.length + intros.filter((i) => i.status === "waiting").length} />
      <SourcesClient initial={sources} />
      <Footer />
    </div>
  );
}
