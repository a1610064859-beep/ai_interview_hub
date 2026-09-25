import type { Metadata, Viewport } from "next";
import { cookies } from "next/headers";
import type { ReactNode } from "react";

import AuthGate from "../components/auth-gate";
import ThemeProvider, { type AppTheme } from "../components/theme-provider";
import "./globals.css";

export const metadata: Metadata = {
  title: "智驾未来 · AI面试仓",
  description: "选择岗位并查看面试首题",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#050912",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const savedTheme = (await cookies()).get("ai-interview-hub-theme")?.value;
  const initialTheme: AppTheme = savedTheme === "night" ? "night" : "day";

  return (
    <html lang="zh-CN" data-theme={initialTheme} suppressHydrationWarning>
      <body className="min-h-dvh overflow-x-hidden antialiased">
        <ThemeProvider initialTheme={initialTheme}>
          <AuthGate>{children}</AuthGate>
        </ThemeProvider>
      </body>
    </html>
  );
}
