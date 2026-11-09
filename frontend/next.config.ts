import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // "standalone" copies only the files needed to run, which keeps the Docker image small.
  output: "standalone",
  reactStrictMode: true,
};

export default nextConfig;
