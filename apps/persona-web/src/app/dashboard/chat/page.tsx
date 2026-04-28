"use client";

import ChatInterface from "@/components/chat/ChatInterface";

/**
 * Home — Aria's primary daily surface (S8 in SCREENS.md).
 * The DashboardShell already gates on auth and onboarding completion,
 * so by the time this renders we know the user has a persona.
 */
export default function HomePage() {
  return <ChatInterface />;
}
