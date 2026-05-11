"use client";

import Link from "next/link";
import { Users } from "lucide-react";
import { Button, EmptyState } from "@/components/ui";

export default function PeoplePage() {
  return (
    <EmptyState
      illustration={<Users />}
      title="Quiet on the network today."
      body="I'll keep looking. I'll message you when someone good shows up."
      action={
        <Link href="/dashboard/brief">
          <Button variant="secondary">Open my brief</Button>
        </Link>
      }
    />
  );
}
