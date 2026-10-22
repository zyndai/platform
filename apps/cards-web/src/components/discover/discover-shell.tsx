import Link from "next/link";
import type { ReactNode } from "react";
import { EDITION_FONT_VARS } from "@/components/editions/fonts";
import { DiscoverNav, type DiscoverPage } from "./discover-nav";
import "./discover.css";

const CRUMBS: Record<DiscoverPage, string> = { directory: "Directory", network: "Network" };

/**
 * The page around Directory and Network: the public card's lavender canvas,
 * its fonts, and a light header in place of the dark site navbar. `main` carries
 * the background so the page owns its canvas on top of the dark site shell.
 * `app` is for a full-height tool (the messenger): less room under the content,
 * and a header that shrinks to the tabs on a phone.
 */
export function DiscoverShell({
  active,
  app = false,
  children,
}: {
  active: DiscoverPage;
  app?: boolean;
  children: ReactNode;
}) {
  return (
    <main className={`dc ${EDITION_FONT_VARS}`}>
      <div className={`dc-wrap${app ? " is-app" : ""}`}>
        <header className="dc-header">
          <div className="dc-crumbs">
            <Link href="/">Zynd</Link>
            {" / "}
            <strong>{CRUMBS[active]}</strong>
          </div>
          <DiscoverNav active={active} />
        </header>
        {children}
      </div>
    </main>
  );
}
