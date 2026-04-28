"use client";

import Link from "next/link";
import { Button, EmptyState } from "@/components/ui";

export default function PeoplePage() {
  return (
    <>
      <div className="topbar">
        <h3>People</h3>
      </div>
      <EmptyState
        title="Quiet on the network today."
        body="I'll keep looking. I'll message you when someone good shows up."
        action={
          <Link href="/dashboard/brief">
            <Button variant="secondary">Open my brief</Button>
          </Link>
        }
      />
    </>
  );
}
