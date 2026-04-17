"use client";

import { useState, useEffect, useRef } from "react";
import { Filter, SortAsc, Inbox, RefreshCw } from "lucide-react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import type { StrongStock } from "@/lib/types";
import { CandidateStockCard } from "./candidate-stock-card";

const MARKET_TABS: { value: string; label: string }[] = [
  { value: "us_stock", label: "美股" },
  { value: "hk_stock", label: "港股" },
  { value: "etf", label: "ETF" },
];

interface CandidateListProps {
  stocks: StrongStock[];
  selectedTicker: string | null;
  watchedTickers?: Set<string>;
  onSelect: (ticker: string) => void;
  onAddWatchlist: (ticker: string) => void;
  onQuickAnalyze?: (ticker: string) => void;
  loading?: boolean;
  conditionSummary?: string;
  activeMarket?: string;
  onMarketChange?: (market: string) => void;
  onRefresh?: () => void;
}

type SortKey = "momentum" | "performance" | "price";

export function CandidateList({
  stocks,
  selectedTicker,
  watchedTickers,
  onSelect,
  onAddWatchlist,
  onQuickAnalyze,
  loading,
  conditionSummary,
  activeMarket = "us_stock",
  onMarketChange,
  onRefresh,
}: CandidateListProps) {
  const [sortBy, setSortBy] = useState<SortKey>("momentum");
  const listRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to selected card when selectedTicker changes (e.g. from chat)
  useEffect(() => {
    if (!selectedTicker || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-ticker="${selectedTicker}"]`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selectedTicker]);

  const sorted = [...stocks].sort((a, b) => {
    if (sortBy === "momentum") return b.momentum_score - a.momentum_score;
    if (sortBy === "performance") return (b.performance_20d ?? 0) - (a.performance_20d ?? 0);
    if (sortBy === "price") return (b.current_price ?? 0) - (a.current_price ?? 0);
    return 0;
  });

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="shrink-0 px-4 py-3 border-b border-theme">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-medium text-theme-primary">候选股票</h2>
          <div className="flex items-center gap-2">
            <span className="text-xs text-theme-muted">{stocks.length} 只</span>
            {onRefresh && (
              <button
                onClick={onRefresh}
                disabled={loading}
                className="p-1 rounded hover:bg-surface-2 text-zinc-500 hover:text-zinc-300 transition-colors disabled:opacity-40"
                title="刷新"
              >
                <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} />
              </button>
            )}
          </div>
        </div>

        {/* Market tabs */}
        <div className="flex items-center gap-1 mb-1.5">
          {MARKET_TABS.map((tab) => (
            <button
              key={tab.value}
              onClick={() => onMarketChange?.(tab.value)}
              className={cn(
                "relative text-[11px] px-2.5 py-1 rounded-md transition-colors duration-200 font-medium",
                activeMarket === tab.value
                  ? "text-brand"
                  : "text-zinc-500 hover:text-zinc-300"
              )}
            >
              {activeMarket === tab.value && (
                <motion.span
                  layoutId="market-tab-pill"
                  className="absolute inset-0 bg-brand/15 rounded-md"
                  transition={{ type: "spring", stiffness: 400, damping: 30 }}
                />
              )}
              <span className="relative z-10">{tab.label}</span>
            </button>
          ))}
        </div>

        {conditionSummary && (
          <p className="text-xs text-zinc-500 flex items-center gap-1">
            <Filter className="w-3 h-3" />
            {conditionSummary}
          </p>
        )}
      </div>

      {/* Sort bar */}
      <div className="shrink-0 px-4 py-2 flex items-center gap-1 border-b border-theme">
        <SortAsc className="w-3 h-3 text-zinc-500 mr-1" />
        {(["momentum", "performance", "price"] as const).map((key) => (
          <button
            key={key}
            onClick={() => setSortBy(key)}
            className={cn(
              "relative text-[11px] px-2 py-0.5 rounded-md transition-colors duration-200",
              sortBy === key
                ? "text-brand"
                : "text-zinc-500 hover:text-zinc-300"
            )}
          >
            {sortBy === key && (
              <motion.span
                layoutId="sort-tab-pill"
                className="absolute inset-0 bg-brand/15 rounded-md"
                transition={{ type: "spring", stiffness: 400, damping: 30 }}
              />
            )}
            <span className="relative z-10">
              {key === "momentum" ? "动量" : key === "performance" ? "20日涨幅" : "当前价格"}
            </span>
          </button>
        ))}
      </div>

      {/* List */}
      <div ref={listRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {loading && (
          <>
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="rounded-xl bg-surface-1 border border-zinc-800/50 p-4 animate-pulse">
                <div className="h-4 bg-surface-2 rounded w-24 mb-2" />
                <div className="h-3 bg-surface-2 rounded w-full mb-1" />
                <div className="h-3 bg-surface-2 rounded w-3/4" />
              </div>
            ))}
          </>
        )}

        {!loading && stocks.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center py-12">
            <Inbox className="w-10 h-10 text-zinc-700 mb-3" />
            <p className="text-sm text-zinc-500">暂无候选股票</p>
            <p className="text-xs text-zinc-600 mt-1">在左侧输入选股需求开始筛选</p>
          </div>
        )}

        {!loading &&
          sorted.map((stock) => (
            <div key={stock.ticker} data-ticker={stock.ticker}>
              <CandidateStockCard
                stock={stock}
                selected={selectedTicker === stock.ticker}
                watching={watchedTickers?.has(stock.ticker)}
                onSelect={onSelect}
                onAddWatchlist={onAddWatchlist}
                onQuickAnalyze={onQuickAnalyze}
              />
            </div>
          ))}
      </div>
    </div>
  );
}
