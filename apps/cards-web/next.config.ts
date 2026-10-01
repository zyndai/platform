import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The landing page used to live at /agent-card (as it still does on the
  // dashboard); here it is the site root.
  async redirects() {
    return [{ source: "/agent-card", destination: "/", permanent: true }];
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
