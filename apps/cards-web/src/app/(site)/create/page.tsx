import type { Metadata } from "next";
import { Suspense } from "react";

import { DiscoverShell } from "@/components/discover/discover-shell";
import { pageMetadata } from "@/lib/seo";
import { CreateBuilder } from "./create-builder";

export const metadata: Metadata = pageMetadata({
  title: "Create your card — Zynd",
  description: "Paste a link and build your AI-discoverable Zynd card on one page. You review everything before it goes live.",
  path: "/create",
});

export default function CreatePage() {
  return (
    <DiscoverShell active="create">
      <Suspense fallback={null}>
        <CreateBuilder />
      </Suspense>
    </DiscoverShell>
  );
}
