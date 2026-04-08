"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useDashboard } from "@/contexts/DashboardContext";

export default function DashboardRedirect() {
  const router = useRouter();
  const { user, loading } = useDashboard();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    if (loading || !user) return;

    const userId = user.id;

    async function checkPersonaAndRedirect() {
      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/persona/${userId}/status`
        );
        if (res.ok) {
          const data = await res.json();
          if (data.deployed) {
            // Returning user — go straight to chat
            router.replace("/dashboard/chat");
            return;
          }
        }
      } catch (e) {
        console.error("Failed to check persona status:", e);
      }

      // First-time user or no persona — onboard them
      router.replace("/dashboard/identity");
      setChecking(false);
    }

    checkPersonaAndRedirect();
  }, [user, loading, router]);

  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--bg-base)",
        gap: "16px",
      }}
    >
      <div className="status-pill">
        <span className="status-dot" />
        Checking identity...
      </div>
      <p
        style={{
          fontFamily: "IBM Plex Mono, monospace",
          fontSize: "10px",
          color: "var(--text-muted)",
          letterSpacing: "1px",
          textTransform: "uppercase",
        }}
      >
        Querying Zynd Network Registry
      </p>
    </div>
  );
}
