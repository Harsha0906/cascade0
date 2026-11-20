/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false,
  // A full analysis (MILP + Monte Carlo + several AI narration calls) can exceed the 30 s default.
  experimental: { proxyTimeout: 120_000 },
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        destination: `${process.env.BACKEND_URL || 'http://localhost:8000'}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
