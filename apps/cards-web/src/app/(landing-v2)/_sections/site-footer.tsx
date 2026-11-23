import Link from "next/link";

const FOOTER_LINKS = [
  // No manifesto page exists yet; until one does, this points at the page's own vision section.
  { label: "Manifesto", href: "#explore" },
  { label: "Discovery Index", href: "/directory" },
  { label: "Agent Specs", href: "/for-ai" },
  { label: "Privacy", href: "/privacy" },
  { label: "Terms", href: "/terms" },
];

// Lives outside the fixed 1440px canvas so it reflows (and stays readable) on any width.
export function SiteFooter() {
  return (
    <footer className="bg-white border-t border-[#e4e4e4] px-4 py-14 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-[1362px] space-y-10">
        <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
          <div className="space-y-2">
            <Link href="/" className="font-extrabold text-[#262627] text-[24px] tracking-[-0.96px]">
              Zynd
            </Link>
            <p className="max-w-md text-[#575757] text-[14px] leading-[1.5]">
              The living professional identity for technical builders and AI agents. Synthesizing digital footprints into sovereign, discoverable assets.
            </p>
          </div>
          <nav aria-label="Footer" className="flex flex-wrap gap-x-7 gap-y-3 max-lg:gap-y-0 text-[#262627] text-[14px]">
            {FOOTER_LINKS.map((link) => (
              <Link key={link.label} href={link.href} className="hover:opacity-60 transition-opacity max-lg:flex max-lg:min-h-[44px] max-lg:items-center max-lg:text-[16px]">
                {link.label}
              </Link>
            ))}
          </nav>
        </div>
        <div className="border-t border-[#ececec] pt-6 text-[#7e7e7e] text-[12px] tracking-[0.04em]">© 2026 ZYND INC. ALL RIGHTS RESERVED.</div>
      </div>
    </footer>
  );
}
