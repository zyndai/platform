import type { Metadata } from "next";
import { Footer, TopBar } from "@/components/dear/ui";
import { getIntros, getPencilled } from "@/lib/dear/repo";
import { InboxClient } from "./inbox-client";

export const metadata: Metadata = { title: "Inbox" };

export default async function InboxPage() {
  const [pencilled, intros] = await Promise.all([getPencilled(), getIntros()]);
  const waiting = intros.filter((i) => i.status === "waiting").length;
  return (
    <div className="shell narrow">
      <TopBar owner current="/dear/inbox" inbox={pencilled.length + waiting} />
      <InboxClient pencilled={pencilled} intros={intros} />
      <Footer />
    </div>
  );
}
