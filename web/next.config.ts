import type { NextConfig } from "next";

const apiMode = readApiMode(process.env.NEXT_PUBLIC_API_MODE);
const backendUrl = apiMode === "real" ? requireBackendUrl() : "";

const nextConfig: NextConfig = {
  async rewrites() {
    if (apiMode !== "real") {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;

function readApiMode(raw: string | undefined): "mock" | "real" {
  if (raw === undefined) {
    return "mock";
  }
  if (raw === "mock" || raw === "real") {
    return raw;
  }
  throw new Error(
    `配置错误：NEXT_PUBLIC_API_MODE 只能是 mock 或 real，当前值为 ${JSON.stringify(raw)}`,
  );
}

function requireBackendUrl(): string {
  const raw = process.env.BACKEND_URL;
  const trimmed = typeof raw === "string" ? raw.trim() : "";
  if (!trimmed) {
    throw new Error("配置错误：real 模式必须设置 BACKEND_URL");
  }
  return trimmed.replace(/\/+$/, "");
}
