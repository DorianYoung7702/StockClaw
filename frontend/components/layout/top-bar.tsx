"use client";

import { useAuth } from "./token-gate";
import { cn } from "@/lib/utils";

const STATIC_GRADIENT = "bg-[linear-gradient(90deg,rgba(16,185,129,0)_0%,rgba(16,185,129,1)_75%,rgba(74,222,128,1)_100%)]";

export function TopBar() {
  const { hasUnlocked, beamKey } = useAuth();

  const beamClass = beamKey === 1 ? "beam-to-gradient" : "beam-replay";

  return (
    <div className="shrink-0 relative">
      <div className="px-3 py-3 sm:px-4 sm:py-4 flex items-center gap-2 sm:gap-2.5">
        <h2 className="text-sm sm:text-base font-bold tracking-tight text-brand">StockClaw</h2>
        <div className="hidden sm:block w-px h-4 bg-brand/60" />
        <span className="hidden sm:inline text-xs text-theme-primary opacity-70">Personalized Stock Screening System</span>
      </div>
      {/* Brand gradient bottom line — key forces remount to replay animation */}
      <div
        key={beamKey}
        className={cn("h-px", hasUnlocked ? beamClass : STATIC_GRADIENT)}
      />
    </div>
  );
}
