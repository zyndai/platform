"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import MessagesPanel from "@/components/MessagesPanel";

// Auth + onboarding-completion are enforced by DashboardShell, so this
// page just renders. Wrapped in Suspense because useSearchParams needs it.
function MessagesContent() {
  const searchParams = useSearchParams();
  const initialThread = searchParams.get("thread");
  return <MessagesPanel initialThreadId={initialThread} />;
}

export default function MessagesPage() {
  return (
    <Suspense fallback={null}>
      <MessagesContent />
    </Suspense>
  );
}
