"use client";
import { useAuth } from "@/hooks/useAuth";

export function EditCardButton({ handle }: { handle: string }) {
  const { authenticated } = useAuth();
  if (!authenticated) return null;
  return (
    <a
      href={`/p/${encodeURIComponent(handle)}/edit`}
      className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full border border-[#7B72E9]/40 bg-[#7B72E9]/10! font-mono text-[12px]! font-semibold text-[#7B72E9]! hover:bg-[#7B72E9]/20! transition-colors"
    >
      Edit my card →
    </a>
  );
}
