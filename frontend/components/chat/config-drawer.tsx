"use client";

import { useEffect, useRef } from "react";
import { X, Check, Settings2 } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import type { ScreeningConfig, SortField } from "@/lib/types";

interface ConfigDrawerProps {
  open: boolean;
  onClose: () => void;
  config: ScreeningConfig;
  onConfigChange: (config: ScreeningConfig) => void;
  onApply: () => void;
}

const MARKET_OPTIONS: { value: ScreeningConfig["market_type"]; label: string }[] = [
  { value: "us_stock", label: "美股" },
  { value: "hk_stock", label: "港股" },
  { value: "etf", label: "ETF" },
];

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

const selectClass =
  "w-full bg-surface-2 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 text-xs focus:outline-none focus:border-brand/50 transition-colors";
const inputClass =
  "w-full bg-surface-2 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-zinc-200 text-xs focus:outline-none focus:border-brand/50 transition-colors";

export function ConfigDrawer({ open, onClose, config, onConfigChange, onApply }: ConfigDrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  const update = (patch: Partial<ScreeningConfig>) => {
    onConfigChange({ ...config, ...patch });
  };

  const handleApply = () => {
    onApply();
    onClose();
  };

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="absolute inset-0 z-30 bg-black/40"
            onClick={onClose}
          />

          {/* Drawer panel */}
          <motion.div
            ref={panelRef}
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
            className="absolute top-0 left-0 bottom-0 z-40 w-72 bg-[var(--bg-base,#09090b)] border-r border-zinc-800/60 flex flex-col shadow-2xl"
          >
            {/* Header */}
            <div className="shrink-0 px-4 py-3 border-b border-zinc-800/40 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Settings2 className="w-4 h-4 text-brand" />
                <span className="text-sm font-medium text-zinc-200">筛选配置</span>
              </div>
              <button
                onClick={onClose}
                className="p-1 rounded hover:bg-surface-2 text-zinc-500 hover:text-zinc-300 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Form */}
            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
              <Field label="市场">
                <select
                  className={selectClass}
                  value={config.market_type}
                  onChange={(e) => update({ market_type: e.target.value as ScreeningConfig["market_type"] })}
                >
                  {MARKET_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </Field>

              <Field label="返回数量">
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    className={inputClass}
                    value={config.top_count}
                    min={1}
                    max={50}
                    onChange={(e) => update({ top_count: Math.max(1, Number(e.target.value) || 1) })}
                  />
                  <span className="text-[10px] text-zinc-500 shrink-0">只/周期</span>
                </div>
              </Field>

              <Field label="RSI 阈值">
                <input
                  type="number"
                  className={inputClass}
                  value={config.rsi_threshold}
                  min={0}
                  max={100}
                  onChange={(e) => update({ rsi_threshold: Math.max(0, Math.min(100, Number(e.target.value) || 0)) })}
                />
              </Field>

              <Field label="动量周期">
                <input
                  type="text"
                  className={inputClass}
                  value={config.momentum_days.join(", ")}
                  onChange={(e) => {
                    const days = e.target.value
                      .split(/[,，\s]+/)
                      .map(Number)
                      .filter((n) => n > 0);
                    if (days.length > 0) update({ momentum_days: days });
                  }}
                />
              </Field>

              <Field label="排序依据">
                <select
                  className={selectClass}
                  value={config.sort_by}
                  onChange={(e) => update({ sort_by: e.target.value as SortField })}
                >
                  {SORT_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </Field>

              <Field label="最低成交额">
                <div className="flex items-center gap-2">
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
                  <span className="text-[10px] text-zinc-500 shrink-0">留空=默认</span>
                </div>
              </Field>
            </div>

            {/* Apply button */}
            <div className="shrink-0 px-4 py-3 border-t border-zinc-800/40">
              <button
                onClick={handleApply}
                className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-brand/15 text-brand text-xs font-medium hover:bg-brand/25 transition-colors"
              >
                <Check className="w-3.5 h-3.5" />
                应用配置并获取强势股
              </button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-[11px] text-zinc-500 mb-1">{label}</label>
      {children}
    </div>
  );
}
