import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "智驾未来 · AI面试仓",
  description: "选择岗位并查看面试首题",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-dvh overflow-x-hidden antialiased">{children}</body>
    </html>
  );
}
