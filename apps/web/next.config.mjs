/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // typedRoutes (experimental) was breaking <Link href={dynamicString}>
  // patterns (MobileNav iterates over an array of href strings). TypeScript
  // gives us route safety where we need it; this flag was more friction than value.
  async rewrites() {
    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
    return [{ source: "/api/backend/:path*", destination: `${apiBase}/api/:path*` }];
  },
};

export default nextConfig;
