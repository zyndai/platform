export interface PublicPersona {
  name: string;
  agent_id: string;
  agent_handle?: string | null;
  description: string;
  capabilities: string[];
  avatar_url?: string | null;
  title?: string | null;
  organization?: string | null;
  location?: string | null;
  visibility?: {
    publicProfile?: boolean;
    calendar?: boolean;
    chat?: boolean;
    contact?: boolean;
  };
}

export function normalizeAvatar(url: string | null | undefined): string | null {
  if (!url) return null;
  return url
    .replace(/=s\d+-c$/, "=s256-c")
    .replace(/\/s\d+-c\//, "/s256-c/");
}

export function hashHue(input: string): number {
  let h = 0;
  for (let i = 0; i < input.length; i++) {
    h = (h * 31 + input.charCodeAt(i)) & 0xffffffff;
  }
  return Math.abs(h) % 360;
}

export function initials(name?: string | null) {
  const parts = (name || "You").trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  return (parts[0]?.slice(0, 2) || "Y").toUpperCase();
}

export function buildSubline(persona: PublicPersona) {
  const role = [persona.title, persona.organization].filter(Boolean).join(" at ");
  return [role, persona.location].filter(Boolean).join(" - ");
}
