"use client";

/** Anchor to the owner-only edit page. The parent only renders this when the
 *  viewer owns the card, so no client auth gate is needed here — rendering an
 *  unconditional <a href> avoids the hydration race where the first click
 *  lands while the button is still being swapped in. */
export function EditCardButton({ handle }: { handle: string }) {
  return (
    <a
      href={`/p/${encodeURIComponent(handle)}/edit`}
      className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full border border-[#7B72E9]/40 bg-[#7B72E9]/10! font-mono text-[12px]! font-semibold text-[#7B72E9]! hover:bg-[#7B72E9]/20! transition-colors"
    >
      Edit my card →
    </a>
  );
}