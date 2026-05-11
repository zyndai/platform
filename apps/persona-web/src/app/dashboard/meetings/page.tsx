"use client";

import Link from "next/link";
import { Calendar } from "lucide-react";
import { Button, EmptyState } from "@/components/ui";

export default function MeetingsPage() {
  return (
    <EmptyState
      illustration={<Calendar />}
      title="No meetings on the books."
      body="Say hi to someone and we'll get something scheduled."
      action={
        <Link href="/dashboard/people">
          <Button variant="secondary">See who&apos;s worth meeting</Button>
        </Link>
      }
    />
  );
}
