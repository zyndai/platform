/**
 * Identity helpers for rendering the signed-in visitor's avatar + name.
 *
 * LinkedIn OIDC stores the profile photo in `user_metadata.picture`, while
 * `avatar_url` is whatever Google left behind (often a default initial
 * image). When the account signed in through LinkedIn, its photo must win.
 */

export interface UserAvatar {
  primary: string;
  /** Tried only if the primary URL fails to load. */
  secondary: string | null;
}

export function pickUserAvatar(md: Record<string, unknown>): UserAvatar {
  const iss = String(md.iss ?? "");
  const avatarUrl = String(md.avatar_url ?? "").trim();
  const picture = String(md.picture ?? "").trim();
  const avatar = String(md.avatar ?? "").trim();
  const linkedin = /linkedin/i.test(iss);

  const primary = linkedin
    ? picture || avatarUrl || avatar
    : avatarUrl || picture || avatar;
  const secondaryCandidates = linkedin
    ? [avatarUrl, avatar]
    : [picture, avatar];
  const secondary = secondaryCandidates.find((u) => u && u !== primary) ?? null;

  return { primary, secondary };
}

export function displayUserName(
  md: Record<string, unknown>,
  email?: string | null,
): string {
  const name =
    String(md.full_name ?? "").trim() ||
    String(md.name ?? "").trim() ||
    String(md.preferred_name ?? "").trim() ||
    (email ? email.split("@")[0] : "");
  return name;
}

export function initialsOf(name: string): string {
  return (
    name
      .split(/\s+/)
      .map((p) => p[0])
      .filter(Boolean)
      .slice(0, 2)
      .join("")
      .toUpperCase() || "?"
  );
}