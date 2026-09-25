"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** /dashboard/settings → defaults to the Accounts tab. */
export default function SettingsRoot() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/dashboard/settings/accounts");
  }, [router]);
  return null;
}
