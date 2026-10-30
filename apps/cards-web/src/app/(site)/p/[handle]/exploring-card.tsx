import type { ExploringItem } from "@/lib/cards";

const KIND_LABEL: Record<ExploringItem["kind"], string> = {
  repo: "Repo",
  paper: "Paper",
  video: "Video",
  post: "Post",
  newsletter: "Newsletter",
  blog: "Blog",
  news: "News",
  link: "Link",
};

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function age(addedAt: string, nowMs: number): string {
  const days = Math.floor((nowMs - Date.parse(addedAt)) / 86400000);
  if (!Number.isFinite(days) || days < 1) return "today";
  return days === 1 ? "yesterday" : `${days}d ago`;
}

/** "Currently exploring": the pages the owner clipped from their browser with Zynd Companion.
 *  Links come from the owner's browser, so only http(s) is drawn and none is followed by search. */
export function ExploringCard({ items, nowMs }: { items: ExploringItem[]; nowMs: number }) {
  const shown = items.filter((item) => /^https?:\/\//.test(item.url)).slice(0, 6);
  if (shown.length === 0) return null;
  return (
    <section
      aria-label="Currently exploring"
      data-section="exploring"
      className="pf-span-12 bg-white border border-[#e2e8f0] rounded-[20px] p-5"
    >
      <div className="flex justify-between items-center text-[0.65rem] font-mono font-bold uppercase tracking-widest text-slate-400 mb-3">
        <span>┌ CURRENTLY EXPLORING</span>
        <span>{shown.length}</span>
      </div>
      <ul className="m-0 p-0 list-none flex flex-col gap-2.5">
        {shown.map((item) => (
          <li key={item.url} className="flex items-start gap-3">
            <span className="shrink-0 mt-0.5 rounded-full bg-[#eef2ff] px-2 py-0.5 font-mono text-[0.6rem] font-bold text-[#4338ca]">
              {KIND_LABEL[item.kind] ?? "Link"}
            </span>
            <div className="min-w-0">
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer nofollow ugc"
                className="block truncate text-sm font-semibold text-slate-900 hover:underline"
              >
                {item.title || host(item.url)}
              </a>
              <div className="font-mono text-[0.65rem] text-slate-400">
                {host(item.url)} · {age(item.added_at, nowMs)}
              </div>
              {item.note && <p className="mt-1 text-sm text-slate-600">{item.note}</p>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
