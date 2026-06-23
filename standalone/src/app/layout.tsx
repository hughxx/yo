import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "问题定位助手",
  description: "本地抓取 → HTML + Markdown 落盘",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
