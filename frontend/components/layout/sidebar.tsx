"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Eye,
  CreditCard,
  Brain,
  Bot,
  Settings2,
  Sun,
  Moon,
  LogOut,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useTheme } from "./theme-provider";
import { useAuth } from "./token-gate";
import { useHelpCenter } from "./help-center";
import { LobsterSvgPaths } from "./logo";
import { useWorkbench } from "@/lib/workbench-context";

const NAV_ITEMS = [
  { href: "/", icon: LayoutDashboard, label: "工作台" },
  { href: "/watchlist", icon: Eye, label: "观察组" },
  { href: "/agent", icon: Bot, label: "Agent" },
  { href: "/memory", icon: Brain, label: "记忆" },
  { href: "/subscription", icon: CreditCard, label: "订阅" },
  { href: "/settings", icon: Settings2, label: "数据源" },
];

export function Sidebar() {
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();
  const { logout, animPhase } = useAuth();
  const { hasUnreadChat, setHasUnreadChat } = useWorkbench();
  const { openHelp } = useHelpCenter();

  return (
    <aside className="fixed bottom-0 left-0 top-auto z-40 h-16 w-full flex flex-row items-center gap-1 border-t border-theme bg-surface-0/95 px-2 backdrop-blur md:left-0 md:top-0 md:h-screen md:w-16 md:flex-col md:gap-0 md:border-r md:border-t-0 md:bg-surface-0 md:px-0 md:py-6 md:backdrop-blur-0">
      {/* Logo — hidden during fly animation (overlay lobster covers this spot), visible after */}
      <button
        type="button"
        onClick={() => {
          openHelp();
          if (pathname === "/") setHasUnreadChat(false);
        }}
        className="flex h-10 w-10 shrink-0 items-center justify-center group relative md:mb-8"
        aria-label="打开快速使用说明"
      >
        <svg
          width="32"
          height="32"
          viewBox="0 0 32 32"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="shrink-0"
          style={{ opacity: animPhase === "logo" ? 0 : 1, transition: "opacity 1s ease" }}
        >
          <LobsterSvgPaths />
        </svg>
        {/* Unread chat badge — pulsing green dot */}
        {hasUnreadChat && pathname !== "/" && (
          <span className="absolute -top-0.5 -right-0.5 flex h-3 w-3">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-brand opacity-60" />
            <span className="relative inline-flex rounded-full h-3 w-3 bg-brand" />
          </span>
        )}
        <span className="absolute left-14 px-2 py-1 rounded-md bg-surface-2 text-xs text-zinc-300 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none">
          {hasUnreadChat && pathname !== "/" ? "💬 对话有新消息" : "点击打开使用说明"}
        </span>
      </button>

      {/* Nav */}
      <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto overflow-y-visible px-1 md:flex-col md:gap-2 md:overflow-visible md:px-0">
        {NAV_ITEMS.map((item) => {
          const active =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => { if (item.href === "/") setHasUnreadChat(false); }}
              className={cn(
                "w-10 h-10 shrink-0 rounded-lg flex items-center justify-center transition-all duration-200 group relative",
                active
                  ? "bg-brand/15 text-brand"
                  : "text-zinc-500 hover:text-zinc-300 hover:bg-surface-2"
              )}
            >
              <item.icon className="w-5 h-5" />
              {/* Tooltip */}
              <span className="absolute left-14 px-2 py-1 rounded-md bg-surface-2 text-xs text-zinc-300 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none">
                {item.label}
              </span>
            </Link>
          );
        })}
      </nav>

      {/* Bottom: Theme toggle + avatar */}
      <div className="flex shrink-0 items-center gap-1 md:flex-col md:gap-3">
        <button
          onClick={toggleTheme}
          className="w-10 h-10 rounded-lg flex items-center justify-center text-zinc-500 hover:text-zinc-300 hover:bg-surface-2 transition-all duration-200 group relative"
        >
          {theme === "dark" ? <Sun className="w-4.5 h-4.5" /> : <Moon className="w-4.5 h-4.5" />}
          <span className="absolute left-14 px-2 py-1 rounded-md bg-surface-2 text-xs text-zinc-300 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none">
            {theme === "dark" ? "浅色模式" : "深色模式"}
          </span>
        </button>
        <div className="hidden md:flex w-8 h-8 rounded-full bg-surface-2 items-center justify-center text-xs text-zinc-400 font-medium">
          U
        </div>
        <button
          onClick={logout}
          className="w-10 h-10 rounded-lg flex items-center justify-center text-zinc-600 hover:text-red-400 hover:bg-surface-2 transition-all duration-200 group relative"
          title="退出登录"
        >
          <LogOut className="w-4 h-4" />
          <span className="absolute left-14 px-2 py-1 rounded-md bg-surface-2 text-xs text-zinc-300 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none">
            退出
          </span>
        </button>
      </div>
    </aside>
  );
}
