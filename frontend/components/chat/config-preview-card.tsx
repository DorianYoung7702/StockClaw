"use client";

import { useState } from "react";
import { Settings2, Check, ChevronUp } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import type { ScreeningConfig, SortField } from "@/lib/types";

interface ConfigPreviewCardProps {
  config: ScreeningConfig;
  onConfigChange?: (config: ScreeningConfig) => void;
  onApply?: () => void;
}

const MARKET_OPTIONS: { value: ScreeningConfig["market_type"]; label: string }[] = [
  { value: "us_stock", label: "美股" },
  { value: "hk_stock", label: "港股" },
  { value: "etf", label: "ETF" },
];

const MARKET_LABELS: Record<string, string> = {
  us_stock: "美股", hk_stock: "港股", etf: "ETF",
};

const SORT_OPTIONS: { value: SortField; label: string }[] = [
  { value: "momentum_score", label: "综合动量评分" },
  { value: "performance_20d", label: "20日涨幅" },
  { value: "performance_40d", label: "40日涨幅" },
  { value: "performance_90d", label: "90日涨幅" },
  { value: "performance_180d", label: "180日涨幅" },
  { value: "rs_20d", label: "相对强度(超额)" },
  { value: "vol_score", label: "量价配合" },
  { value: "trend_r2", label: "趋势平滑度" },
  { value: "volume_5d_avg", label: "5日成交额" },
];

const SORT_LABELS: Record<string, string> = Object.fromEntries(
  SORT_OPTIONS.map((o) => [o.value, o.label])
);

const selectClass =
  "bg-surface-2 border border-zinc-700 rounded px-1.5 py-0.5 text-zinc-200 text-xs focus:outline-none focus:border-brand/50";
const inputClass =
  "bg-surface-2 border border-zinc-700 rounded px-1.5 py-0.5 text-zinc-200 text-xs w-16 focus:outline-none focus:border-brand/50";

export function ConfigPreviewCard({ config, onConfigChange, onApply }: ConfigPreviewCardProps) {
  const [collapsed, setCollapsed] = useState(false);

  const update = (patch: Partial<ScreeningConfig>) => {
    onConfigChange?.({ ...config, ...patch });
  };

  return (
    <div className="rounded-xl bg-surface-1 border border-zinc-800/50 overflow-hidden">
      {/* Header — always visible, click to toggle */}
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-surface-2/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Settings2 className="w-3.5 h-3.5 text-brand shrink-0" />
          <span className="text-xs font-medium text-zinc-300">筛选配置</span>
          {collapsed && (
            <span className="text-[11px] text-zinc-500">
              {MARKET_LABELS[config.market_type]} · {config.top_count}只 · RSI&gt;{config.rsi_threshold} · {SORT_LABELS[config.sort_by]}
            </span>
          )}
        </div>
        <motion.div
          animate={{ rotate: collapsed ? 180 : 0 }}
          transition={{ duration: 0.25, ease: "easeInOut" }}
        >
          <ChevronUp className="w-3.5 h-3.5 text-zinc-500" />
        </motion.div>
      </button>

      {/* Collapsible body */}
      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.div
            key="body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3">
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs items-center">
                <div className="text-zinc-500">市场</div>
                <select
                  className={selectClass}
                  value={config.market_type}
                  onChange={(e) => update({ market_type: e.target.value as ScreeningConfig["market_type"] })}
                >
                  {MARKET_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>

                <div className="text-zinc-500">返回数量</div>
                <div className="flex items-center gap-1">
                  <input
                    type="number"
                    className={inputClass}
                    value={config.top_count}
                    min={1}
                    max={50}
                    onChange={(e) => update({ top_count: Math.max(1, Number(e.target.value) || 1) })}
                  />
                  <span className="text-zinc-500">只/周期</span>
                </div>

                <div className="text-zinc-500">RSI 阈值</div>
                <input
                  type="number"
                  className={inputClass}
                  value={config.rsi_threshold}
                  min={0}
                  max={100}
                  onChange={(e) => update({ rsi_threshold: Math.max(0, Math.min(100, Number(e.target.value) || 0)) })}
                />

                <div className="text-zinc-500">动量周期</div>
                <input
                  type="text"
                  className={`${selectClass} w-full`}
                  value={config.momentum_days.join(", ")}
                  onChange={(e) => {
                    const days = e.target.value
                      .split(/[,，\s]+/)
                      .map(Number)
                      .filter((n) => n > 0);
                    if (days.length > 0) update({ momentum_days: days });
                  }}
                />

                <div className="text-zinc-500">排序依据</div>
                <select
                  className={`${selectClass} w-full`}
                  value={config.sort_by}
                  onChange={(e) => update({ sort_by: e.target.value as SortField })}
                >
                  {SORT_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>

                <div className="text-zinc-500">最低成交额</div>
                <div className="flex items-center gap-1">
                  <input
                    type="number"
                    className={inputClass}
                    placeholder="自动"
                    value={config.min_volume_turnover ?? ""}
                    onChange={(e) => {
                      const v = e.target.value ? Number(e.target.value) : undefined;
                      update({ min_volume_turnover: v });
                    }}
                  />
                  <span className="text-zinc-500 text-[10px]">留空=默认</span>
                </div>
              </div>

              {onApply && (
                <button
                  onClick={(e) => { e.stopPropagation(); onApply(); }}
                  className="mt-3 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-brand/15 text-brand text-xs font-medium hover:bg-brand/25 transition-colors"
                >
                  <Check className="w-3 h-3" />
                  应用配置并获取强势股
                </button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
