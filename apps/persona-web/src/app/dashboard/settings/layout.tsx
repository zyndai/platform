"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/dashboard/settings/accounts", label: "Accounts" },
  { href: "/dashboard/settings/you",      label: "You" },
];

export default function SettingsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  return (
    <>
      <div className="topbar">
        <h3>Settings</h3>
      </div>
      <nav className="tabs" aria-label="Settings sections">
        {TABS.map((t) => {
          const active = pathname === t.href || pathname.startsWith(t.href + "/");
          return (
            <Link
              key={t.href}
              href={t.href}
              className={`tab ${active ? "active" : ""}`}
            >
              {t.label}
            </Link>
          );
        })}
      </nav>
      <div className="settings-body">{children}</div>
    </>
  );
}
