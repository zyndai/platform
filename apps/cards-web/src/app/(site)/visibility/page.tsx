import type { Metadata } from "next";

import { DiscoverShell } from "@/components/discover/discover-shell";
import { pageMetadata } from "@/lib/seo";
import { VisibilityChecker } from "./visibility-checker";
import "./visibility.css";

export const metadata: Metadata = pageMetadata({
  title: "What does AI say about you? — Zynd",
  description:
    "Type your name and see what an AI with web search says about you today, and whether it can find your Zynd card.",
  path: "/visibility",
});

export default function VisibilityPage() {
  return (
    <DiscoverShell active="visibility">
      <VisibilityChecker />
    </DiscoverShell>
  );
}
