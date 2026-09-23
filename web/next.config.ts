import type { NextConfig } from "next";

const apiMode = readApiMode(process.env.NEXT_PUBLIC_API_MODE);
const backendUrl = apiMode === "real" ? requireBackendUrl() : "";

const nextConfig: NextConfig = {
  // Backend total budget is 300s; allow bounded subprocess cancellation and transport overhead.
  experimental: {
    proxyTimeout: readProxyTimeout(process.env.API_PROXY_TIMEOUT_MS),
  },
  async rewrites() {
    if (apiMode !== "real") {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
      {
        source: "/audio/:path*",
        destination: `${backendUrl}/audio/:path*`,
      },
    ];
  },
};

export default nextConfig;

function readProxyTimeout(raw: string | undefined): number {
  const value = Number(raw ?? "360000");
  if (!Number.isFinite(value) || value < 1000) throw new Error("API_PROXY_TIMEOUT_MS 必须为至少 1000 的毫秒数");
  return value;
}

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
