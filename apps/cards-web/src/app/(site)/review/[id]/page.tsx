import type { Metadata } from "next";
import { ProposalReview } from "@/components/mcp/ProposalReview";

export const metadata: Metadata = {
  title: "Review assistant proposal",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default async function ReviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ProposalReview id={id} />;
}
