import { imgProxyUrl } from "@/lib/avatar";
import type { WorkItem } from "@/lib/cards";

const TILES_SHOWN = 6;

/** Project covers from a design portfolio (Behance, Dribbble), shown as a grid of tiles that link out. */
export function WorkGallery({ items, safeUrl }: { items: WorkItem[]; safeUrl: (url: string | null | undefined) => string | null }) {
  const shown = items.filter((i) => i.image_url).slice(0, TILES_SHOWN);
  if (shown.length === 0) return null;
  const source = shown[0].source ? shown[0].source.toUpperCase() : "PORTFOLIO";
  return (
    <div className="pf-span-12 pf-gallery" style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 20, padding: "20px 24px" }}>
      <div className="pf-mono flex justify-between items-center mb-4" style={{ fontSize: "0.65rem" }}>
        <span style={{ color: "#6b63ff", fontWeight: 700 }}>┌ WORK</span>
        <span style={{ background: "#e0e7ff", color: "#4f46e5", padding: "3px 10px", borderRadius: 99, fontWeight: 700 }}>
          {source} · {shown.length} {shown.length === 1 ? "PROJECT" : "PROJECTS"} ┐
        </span>
      </div>
      <ul className="pf-gallery-grid">
        {shown.map((item) => {
          const href = safeUrl(item.url);
          const tile = (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element -- remote project covers, proxied; sizes are unknown */}
              <img src={imgProxyUrl(item.image_url)} alt={item.title} loading="lazy" />
              {item.title && <span className="pf-gallery-title">{item.title}</span>}
            </>
          );
          return (
            <li key={item.image_url} className="pf-gallery-tile">
              {href ? <a href={href} target="_blank" rel="noreferrer">{tile}</a> : tile}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
