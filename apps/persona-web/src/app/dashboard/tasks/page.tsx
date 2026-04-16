"use client";

import { useDashboard } from "@/contexts/DashboardContext";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import TasksPanel from "@/components/TasksPanel";

export default function TasksPage() {
  const { hasPersona, personaLoading } = useDashboard();
  const router = useRouter();

  useEffect(() => {
    if (!personaLoading && !hasPersona) {
      router.replace("/dashboard/identity");
    }
  }, [hasPersona, personaLoading, router]);

  if (personaLoading || !hasPersona) return null;

  return <TasksPanel />;
}
