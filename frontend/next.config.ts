import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a standalone server bundle (.next/standalone + a minimal server.js)
  // that traces only the node_modules it needs, for a small production image.
  // The Dockerfile copies public/ and .next/static in separately — server.js
  // does not bundle them.
  output: "standalone",
};

export default nextConfig;
