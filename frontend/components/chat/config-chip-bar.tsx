"use client";

import { Settings2, Play } from "lucide-react";
import type { ScreeningConfig } from "@/lib/types";

interface ConfigChipBarProps {
  config: ScreeningConfig;
  onOpenDrawer: () => void;
  onApply?: () => void;
  applyLoading?: boolean;
}

const MARKET_LABELS: Record<string, string> = {
  us_stock: "美股",
  hk_stock: "港股",
  etf: "ETF",
};

const SORT_SHORT: Record<string, string> = {
  momentum_score: "动量",
  performance_20d: "20日涨幅",
  performance_40d: "40日涨幅",
  performance_90d: "90日涨幅",
  performance_180d: "180日涨幅",
  rs_20d: "超额",
  vol_score: "量价",
  trend_r2: "趋势R²",
  volume_5d_avg: "成交额",
};

export function ConfigChipBar({ config, onOpenDrawer, onApply, applyLoading }: ConfigChipBarProps) {
  const chips = [
    MARKET_LABELS[config.market_type] || config.market_type,
    `${config.top_count}只`,
    `RSI>${config.rsi_threshold}`,
    SORT_SHORT[config.sort_by] || config.sort_by,
  ];

  return (
    <div className="shrink-0 flex items-center justify-end gap-1.5 px-4 py-1.5 border-t border-zinc-800/40">
      <div className="flex items-center gap-1 overflow-x-auto scrollbar-none">
        {chips.map((label, i) => (
          <button
            key={i}
            onClick={onOpenDrawer}
            className="shrink-0 px-2 py-0.5 rounded-md bg-surface-2/60 border border-zinc-800/40 text-[11px] text-zinc-400 hover:text-zinc-200 hover:border-zinc-700 transition-colors"
          >
            {label}
          </button>
        ))}
      </div>
      <button
        onClick={onOpenDrawer}
        className="shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-surface-2/60 border border-zinc-800/40 text-[11px] text-zinc-400 hover:text-zinc-200 hover:border-zinc-700 transition-colors"
      >
        <Settings2 className="w-3 h-3" />
        配置
      </button>
      {onApply && (
        <button
          onClick={onApply}
          disabled={applyLoading}
          className="shrink-0 inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md bg-brand/15 border border-brand/25 text-[11px] font-medium text-brand hover:bg-brand/25 hover:border-brand/35 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Play className="w-3 h-3" />
          {applyLoading ? "获取中..." : "应用配置"}
        </button>
      )}
    </div>
  );
}
