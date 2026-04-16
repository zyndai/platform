"use client";

import { useDashboard } from "@/contexts/DashboardContext";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import ChatInterface from "@/components/ChatInterface";

export default function ChatPage() {
  const { hasPersona, personaLoading } = useDashboard();
  const router = useRouter();

  useEffect(() => {
    if (!personaLoading && !hasPersona) {
      router.replace("/dashboard/identity");
    }
  }, [hasPersona, personaLoading, router]);

  if (personaLoading || !hasPersona) return null;

  return <ChatInterface />;
}
