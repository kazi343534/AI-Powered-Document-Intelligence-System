import type { NextConfig } from "next";

const rawBackend = process.env.BACKEND_URL || "http://localhost:8000";
// Sanitize: strip any wrapping brackets/quotes and trailing slash
const backend = rawBackend
  .replace(/^[\[\]"']+|[\[\]"']+$/g, "")
  .replace(/\/$/, "");

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*`,
      },
      {
        source: "/health/:path*",
        destination: `${backend}/health/:path*`,
      },
    ];
  },
};

export default nextConfig;
