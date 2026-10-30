import Link from "next/link";
import type { Helped } from "@/lib/cards";

/** "Helped": people this card's owner helped through asks. A credit is the asker's choice (they
 *  picked who helped) and the helper can hide it, so only visible ones reach this component. */
export function HelpedCard({ helped }: { helped?: Helped }) {
  if (!helped || helped.count < 1 || helped.items.length === 0) return null;
  return (
    <section
      aria-label="Helped"
      data-section="helped"
      className="pf-span-12 bg-white border border-[#e2e8f0] rounded-[20px] p-5"
    >
      <div className="flex justify-between items-center text-[0.65rem] font-mono font-bold uppercase tracking-widest text-slate-400 mb-3">
        <span>┌ HELPED</span>
        <span>{helped.count}</span>
      </div>
      <p className="m-0 mb-3 text-sm font-semibold text-slate-900">
        Helped {helped.count} {helped.count === 1 ? "person" : "people"} on Zynd
      </p>
      <ul className="m-0 p-0 list-none flex flex-col gap-2">
        {helped.items.map((item) => (
          <li key={`${item.asker_handle}:${item.ask}`} className="text-sm text-slate-600">
            Helped{" "}
            <Link
              href={`/p/${encodeURIComponent(item.asker_handle)}`}
              className="font-semibold text-slate-900 hover:underline"
            >
              {item.asker_name}
            </Link>{" "}
            with &ldquo;{item.ask}&rdquo;
          </li>
        ))}
      </ul>
    </section>
  );
}
