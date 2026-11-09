import type { NextConfig } from "next";

// Static export: the UI is plain files that any web server (or the nginx
// container in docker-compose) can serve; all data comes from the FastAPI API.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
