/** @type {import('next').NextConfig} */
const backendBaseUrl =
  (process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:9000").replace(
    /\/+$/,
    ""
  );

const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendBaseUrl}/:path*`,
      },
      {
        source: "/workspace/download",
        destination: `${backendBaseUrl}/workspace/download`,
      },
    ];
  },
  webpack: (config, { isServer }) => {
    // 配置 Monaco Editor 使用本地资源
    if (!isServer) {
      config.resolve.fallback = {
        ...config.resolve.fallback,
        fs: false,
        net: false,
        tls: false,
      };
    }
    return config;
  },
}

export default nextConfig
