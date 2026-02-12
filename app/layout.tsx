import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Z哥量化回测系统",
  description: "A股量化交易回测系统 - 策略配置、回测运行、结果分析",
};

export const viewport: Viewport = {
  themeColor: "#0f1117",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN" className="dark">
      <head>
        <Script
          src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"
          strategy="beforeInteractive"
        />
      </head>
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} font-sans antialiased`}
      >
        <div className="flex h-screen overflow-hidden">
          <Sidebar />
          <main className="flex-1 overflow-auto scrollbar-thin">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
