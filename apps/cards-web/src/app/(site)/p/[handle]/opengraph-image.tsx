import { ImageResponse } from "next/og";
import { fetchCardByHandle } from "@/lib/cards";

export const revalidate = 3600;

export const alt = "Zynd Card profile";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

interface ImageProps {
  params: Promise<{ handle: string }>;
}

export default async function Image({ params }: ImageProps) {
  const { handle } = await params;
  const card = await fetchCardByHandle(handle);

  const name = card?.identity?.name?.trim() || "Zynd Card";
  const headline = card?.identity?.headline?.trim() || "One living profile for people and AI";
  const accentLine =
    (card?.working_on ?? []).filter(Boolean)[0] ||
    (card?.can_help_with ?? []).filter(Boolean)[0] ||
    card?.summary?.trim() ||
    "";
  const initials = name
    .split(/\s+/)
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();

  let avatar: string | null = null;
  const avatarUrl = card?.identity?.avatar_url;
  if (avatarUrl && /^https?:\/\//.test(avatarUrl)) {
    try {
      const res = await fetch(avatarUrl, { signal: AbortSignal.timeout(3000) });
      if (res.ok) {
        const buf = Buffer.from(await res.arrayBuffer());
        const mime = res.headers.get("content-type") || "image/jpeg";
        avatar = `data:${mime};base64,${buf.toString("base64")}`;
      }
    } catch {
      avatar = null;
    }
  }

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          background: "linear-gradient(120deg, #1e1b4b 0%, #312e81 55%, #4f46e5 100%)",
          color: "#fff",
          fontFamily: "sans-serif",
          padding: 56,
          position: "relative",
        }}
      >
        {/* corner brand */}
        <div style={{ position: "absolute", top: 40, left: 56, display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 26, height: 26, borderRadius: 8, background: "#7b72e9", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, fontWeight: 800 }}>
            Z
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: 2 }}>ZYND CARDS</div>
        </div>
        <div style={{ position: "absolute", top: 46, right: 56, display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#34d399" }} />
          <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: 3, color: "#a7f3d0" }}>LIVE PROFILE</div>
        </div>

        {/* main */}
        <div style={{ display: "flex", alignItems: "center", gap: 32, marginTop: 96 }}>
          {avatar ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={avatar} width={120} height={120} style={{ borderRadius: 24, objectFit: "cover" }} alt="" />
          ) : (
            <div style={{ width: 120, height: 120, borderRadius: 24, background: "rgba(255,255,255,0.14)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 40, fontWeight: 800, color: "#c7d2fe" }}>
              {initials}
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 64, fontWeight: 800, lineHeight: 1.05 }}>{name}</div>
            <div style={{ fontSize: 28, color: "#c7d2fe", marginTop: 10, fontWeight: 600 }}>{headline}</div>
            {accentLine && (
              <div style={{ display: "flex", marginTop: 18 }}>
                <div style={{ fontSize: 18, color: "#e0e7ff", background: "rgba(255,255,255,0.12)", borderRadius: 99, padding: "8px 16px" }}>
                  {accentLine.length > 90 ? `${accentLine.slice(0, 87)}…` : accentLine}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* footer */}
        <div style={{ position: "absolute", bottom: 40, left: 56, right: 56, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 20, color: "#a5b4fc", fontWeight: 600 }}>cards.zynd.ai/p/{card?.handle || handle}</div>
          <div style={{ fontSize: 18, color: "rgba(255,255,255,0.55)", letterSpacing: 2 }}>
            ONE PROFILE · FOR PEOPLE AND AI
          </div>
        </div>
      </div>
    ),
    { ...size },
  );
}