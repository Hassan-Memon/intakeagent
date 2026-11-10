import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // "standalone" copies only the files needed to run, which keeps the Docker image small.
  output: "standalone",
  reactStrictMode: true,
  env: {
    // Always defined so `process.env.NEXT_PUBLIC_DEMO_MODE === "1"` is replaced by a literal at
    // build time and the in-browser demo backend (lib/demo) is dropped from normal builds.
    NEXT_PUBLIC_DEMO_MODE: process.env.NEXT_PUBLIC_DEMO_MODE === "1" ? "1" : "0",
  },
};

export default nextConfig;
