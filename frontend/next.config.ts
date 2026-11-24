import type { NextConfig } from "next";

// Static export: the UI is plain files that any web server (or the nginx
// container in docker-compose) can serve; all data comes from the FastAPI API.
const nextConfig: NextConfig = {
  output: "export",
  // Set only for the GitHub Pages demo, which is served under /<repository>/.
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || undefined,
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
