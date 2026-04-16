"use client";

import { useDashboard } from "@/contexts/DashboardContext";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import MessagesPanel from "@/components/MessagesPanel";

export default function MessagesPage() {
  const { hasPersona, personaLoading } = useDashboard();
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialThread = searchParams.get("thread");

  useEffect(() => {
    if (!personaLoading && !hasPersona) {
      router.replace("/dashboard/identity");
    }
  }, [hasPersona, personaLoading, router]);

  if (personaLoading || !hasPersona) return null;

  return <MessagesPanel initialThreadId={initialThread} />;
}
