import type { Metadata } from "next";
import { ReviewerSignIn } from "./reviewer-sign-in";

export const metadata: Metadata = {
  title: "Reviewer sign-in",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function ReviewerAuthPage() {
  return <ReviewerSignIn />;
}
