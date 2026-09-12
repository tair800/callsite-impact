import type { NextConfig } from "next";

/**
 * Deliberately small.
 *
 * `IMPACT_API_BASE_URL` is **not** listed under `env` and must never be: anything placed there is
 * inlined into the client bundle at build time, and the console's API address is a server-side
 * concern. It is read in exactly one module — `lib/source.ts`, which imports `server-only` — and
 * every page that needs it is a server component.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
