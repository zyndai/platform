"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { useMyCard } from "@/hooks/useMyCard";
import { imgProxyUrl } from "@/lib/avatar";
import { displayUserName, initialsOf, pickUserAvatar } from "@/lib/identity";

/** Who is signed in: photo, name, sign out. Same facts as the profile page's account chip. */
function AccountChip() {
  const { user, logout } = useAuth();
  const { card } = useMyCard();
  const [failed, setFailed] = useState(false);

  const md = (user?.user_metadata ?? {}) as Record<string, unknown>;
  const { primary, secondary } = pickUserAvatar(md);
  const avatarSrc = imgProxyUrl(primary, secondary);
  const name = (card?.identity?.name ?? "").trim() || displayUserName(md, user?.email);

  return (
    <span className="dc-account">
      {avatarSrc && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={avatarSrc} alt="" className="dc-account-photo" onError={() => setFailed(true)} />
      ) : (
        <span className="dc-account-initials" aria-hidden="true">{initialsOf(name)}</span>
      )}
      <span className="dc-account-name">{name}</span>
      <button type="button" onClick={() => void logout()} aria-label="Sign out" title="Sign out">
        Sign out
      </button>
    </span>
  );
}

export type DiscoverPage = "directory" | "network" | "create";

/** Right side of the Directory / Network / Create header: where to go, and who you are. */
export function DiscoverNav({ active }: { active: DiscoverPage }) {
  const { authenticated } = useAuth();
  const { handle } = useMyCard();
  const pathname = usePathname();

  return (
    <nav className="dc-nav" aria-label="Cards">
      <div className="dc-tabs">
        <Link href="/directory" className="dc-tab" aria-current={active === "directory" ? "page" : undefined}>Directory</Link>
        {(authenticated || active === "network") && (
          <Link href="/network" className="dc-tab" aria-current={active === "network" ? "page" : undefined}>Network</Link>
        )}
      </div>
      <Link href="/for-ai" className="dc-navlink">For AI</Link>
      {authenticated && handle && (
        <Link href={`/p/${encodeURIComponent(handle)}`} className="dc-pill">My card</Link>
      )}
      {!authenticated && (
        <Link href={`/auth?next=${encodeURIComponent(pathname || "/directory")}`} className="dc-pill">Sign in</Link>
      )}
      {!handle && active !== "create" && <Link href="/create" className="dc-cta">Create your card</Link>}
      {authenticated && <AccountChip />}
    </nav>
  );
}
