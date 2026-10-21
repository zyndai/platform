import Link from "next/link";
import type { ReactNode } from "react";

import { Navbar } from "@/components/Navbar";

const LINK = "text-[#5b7cfa] underline underline-offset-4 hover:text-white";

export function LegalPage({
  title,
  updated,
  children,
}: {
  title: string;
  updated: string;
  children: ReactNode;
}) {
  return (
    <>
      <Navbar />
      <article className="text-white selection:bg-[#5b7cfa]/30 antialiased font-sans pb-32">
        <div className="mx-auto w-full max-w-[720px] px-6 pt-12">
          <header className="mb-12">
            <h1 className="text-4xl font-bold text-white md:text-5xl">{title}</h1>
            <p className="mt-4 text-sm text-zinc-500">Last updated: {updated}</p>
          </header>
          {children}
          <nav aria-label="Legal" className="mt-16 flex flex-wrap gap-x-4 gap-y-2 text-sm text-zinc-500">
            <span>&copy; Zynd AI Inc</span>
            <Link href="/privacy" className={LINK}>Privacy Policy</Link>
            <Link href="/terms" className={LINK}>Terms of Service</Link>
            <Link href="/support" className={LINK}>Support</Link>
          </nav>
        </div>
      </article>
    </>
  );
}

export function LegalSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-10 space-y-4 leading-relaxed text-zinc-300">
      <h2 className="text-lg font-bold text-white">{title}</h2>
      {children}
    </section>
  );
}

export function LegalList({ children }: { children: ReactNode }) {
  return <ul className="list-disc space-y-2 pl-5">{children}</ul>;
}

export function LegalLink({ href, children }: { href: string; children: ReactNode }) {
  // Internal paths route client-side; mailto: and other schemes need a plain anchor.
  return href.startsWith("/") ? (
    <Link href={href} className={LINK}>
      {children}
    </Link>
  ) : (
    <a href={href} className={LINK}>
      {children}
    </a>
  );
}
