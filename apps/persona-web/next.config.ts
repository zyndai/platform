import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  transpilePackages: ['react-markdown', 'remark-gfm', 'vfile', 'unified', 'mdast-util-from-markdown', 'mdast-util-to-string', 'micromark', 'decode-named-character-reference'],
  allowedDevOrigins: ['zyndpersona.shortblogs.org'],
};

export default nextConfig;
