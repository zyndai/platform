"use client";

import { useDashboard } from "@/contexts/DashboardContext";
import PersonaBuilder from "@/components/PersonaBuilder";

export default function IdentityPage() {
  const { user } = useDashboard();
  return <PersonaBuilder userId={user?.id || ""} />;
}
