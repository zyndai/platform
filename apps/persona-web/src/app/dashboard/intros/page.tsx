import { notFound } from "next/navigation";
import { IntroInbox } from "./intro-inbox";

export default function IntrosPage() {
  if (process.env.NEXT_PUBLIC_FEATURE_S12_INTROS !== "true") notFound();
  return <IntroInbox />;
}
