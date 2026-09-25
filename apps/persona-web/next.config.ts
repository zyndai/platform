import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  transpilePackages: ['react-markdown', 'remark-gfm', 'vfile', 'unified', 'mdast-util-from-markdown', 'mdast-util-to-string', 'micromark', 'decode-named-character-reference'],
  allowedDevOrigins: ['persona.zynd.ai'],

  // Security headers for agent-published pages. script-src is disabled
  // because the content is user/agent-generated HTML.
  async headers() {
    return [
      {
        source: "/pages/:slug*",
        headers: [
          {
            key: "Content-Security-Policy",
            value: (
              "default-src 'self'; " +
              "script-src 'self'; " +
              "style-src 'self' 'unsafe-inline'; " +
              "img-src 'self' data: https:; " +
              "font-src 'self' https:; " +
              "connect-src 'self'; " +
              "object-src 'none'; " +
              "base-uri 'self'; " +
              "frame-ancestors 'none';"
            ),
          },
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
