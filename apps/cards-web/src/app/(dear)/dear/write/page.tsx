import type { Metadata } from "next";
import { TopBar } from "@/components/dear/ui";
import { WriteClient } from "./write-client";

export const metadata: Metadata = { title: "Write your letter" };

export default function WritePage() {
  return (
    <div className="shell narrow">
      <TopBar current="/dear/write" />
      <WriteClient />
    </div>
  );
}
