import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import AuthGate from "../components/auth-gate";
import ThemeProvider from "../components/theme-provider";
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

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" data-theme="day" suppressHydrationWarning>
      <body className="min-h-dvh overflow-x-hidden antialiased">
        <ThemeProvider>
          <AuthGate>{children}</AuthGate>
        </ThemeProvider>
      </body>
    </html>
  );
}
