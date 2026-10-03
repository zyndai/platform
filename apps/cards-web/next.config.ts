import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The landing page used to live at /agent-card (as it still does on the
  // dashboard); here it is the site root.
  async redirects() {
    return [
      { source: "/agent-card", destination: "/", permanent: true },
      // The footer's AGENT_API link used to point at /p/<handle>/agent, which
      // never had a route (it 404'd on the dashboard too). The machine-readable
      // card is data.json; keep already-shared /agent URLs working.
      { source: "/p/:handle/agent", destination: "/p/:handle/data.json", permanent: false },
    ];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
