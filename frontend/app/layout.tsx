import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/layout/sidebar";
import { TopBar } from "@/components/layout/top-bar";
import { HelpCenterProvider } from "@/components/layout/help-center";
import { ThemeProvider } from "@/components/layout/theme-provider";
import { TokenGate } from "@/components/layout/token-gate";
import { WorkbenchProvider } from "@/lib/workbench-context";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "StockClaw — AI 自选股工作台",
  description: "用自然语言配置监控、查看候选股、快速看懂基本面",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN" className="dark" suppressHydrationWarning>
      <body className={inter.className}>
        <ThemeProvider>
          <TokenGate>
            <WorkbenchProvider>
              <HelpCenterProvider>
                <Sidebar />
                <main className="h-screen pb-16 md:pb-0 md:ml-16 flex flex-col overflow-hidden">
                  <TopBar />
                  <div className="flex-1 overflow-hidden">{children}</div>
                </main>
              </HelpCenterProvider>
            </WorkbenchProvider>
          </TokenGate>
        </ThemeProvider>
      </body>
    </html>
  );
}
