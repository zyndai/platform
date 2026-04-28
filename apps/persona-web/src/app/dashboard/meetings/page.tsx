"use client";

import Link from "next/link";
import { Button, EmptyState } from "@/components/ui";

export default function MeetingsPage() {
  return (
    <>
      <div className="topbar">
        <h3>Meetings</h3>
      </div>
      <EmptyState
        title="No meetings on the books."
        body="Say hi to someone and we'll get something scheduled."
        action={
          <Link href="/dashboard/people">
            <Button variant="secondary">See who&apos;s worth meeting</Button>
          </Link>
        }
      />
    </>
  );
}
