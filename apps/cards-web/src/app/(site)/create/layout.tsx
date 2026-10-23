import type { Metadata } from "next";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Add your profiles — Zynd Cards",
  description:
    "Paste links to your GitHub, LinkedIn, X, or any website. Zynd scrapes what's public and builds your card — you approve before anything goes live.",
  path: "/create",
});

export default function CreateLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
