import Link from "next/link";
import { Eye } from "lucide-react";
import { lensStyles, lensSummary, type Lens, type LensCardFields } from "@/lib/lenses";

/** The "Viewing as …" line on a lens URL, plus the stylesheet that arranges the
 *  grid below it for that reader (lib/lenses.ts). */
export function LensBar({ lens, card, fullCardHref }: { lens: Lens; card: LensCardFields; fullCardHref: string }) {
  const summary = lensSummary(lens, card);
  return (
    <>
      <style>{`
        ${lensStyles(lens)}
        .pf-lens { display: flex; align-items: center; gap: 12px 16px; flex-wrap: wrap; margin: 0 0 16px; padding: 12px 16px; background: #fff; border: 1px solid #c7d2fe; border-radius: 16px; color: #0f172a; }
        .pf-lens-icon { flex-shrink: 0; display: grid; place-items: center; width: 32px; height: 32px; border-radius: 10px; background: #eef0ff; color: #4f46e5; }
        .pf-lens-text { flex: 1 1 260px; min-width: 0; margin: 0; font-size: 0.85rem; line-height: 1.5; }
        .pf-lens-text strong { font-weight: 800; }
        .pf-lens-text span { color: #475569; }
        .pf-lens-full { flex-shrink: 0; font-size: 0.8rem; font-weight: 700; color: #4338ca; text-decoration: underline; text-underline-offset: 3px; }
        .pf-lens-full:focus-visible { outline: 3px solid #4338ca; outline-offset: 3px; border-radius: 4px; }
      `}</style>
      <aside className="pf-lens" aria-label={`This card, arranged for ${lens.audience}`}>
        <span className="pf-lens-icon" aria-hidden="true"><Eye size={16} /></span>
        <p className="pf-lens-text">
          <strong>Viewing as {lens.viewer}.</strong>
          {summary && <span> {summary}</span>}
        </p>
        <Link className="pf-lens-full" href={fullCardHref}>See the full card</Link>
      </aside>
    </>
  );
}
