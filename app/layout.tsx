import type { Metadata, Viewport } from "next";
import { Noto_Sans_SC, JetBrains_Mono } from "next/font/google";
import { Sidebar } from "@/components/layout/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const notoSans = Noto_Sans_SC({
  subsets: ["latin"],
  variable: "--font-sans",
  weight: ["400", "500", "600", "700"],
});

const jetBrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "Z哥回测系统 - 股票交易策略回测平台",
  description:
    "基于Z哥战法的A股策略回测系统，支持多策略选股、组合卖出策略、绩效分析与策略排名",
};

export const viewport: Viewport = {
  themeColor: "#0f1419",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN" className="dark">
      <body
        className={`${notoSans.variable} ${jetBrainsMono.variable} font-sans antialiased`}
      >
        <TooltipProvider>
          <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 pl-60">
              <div className="mx-auto max-w-7xl p-6">{children}</div>
            </main>
          </div>
        </TooltipProvider>
      </body>
    </html>
  );
}
