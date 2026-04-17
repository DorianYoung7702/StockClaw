"use client";

import { Plus, Check, ChevronRight, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import type { StrongStock } from "@/lib/types";

interface CandidateStockCardProps {
  stock: StrongStock;
  selected?: boolean;
  watching?: boolean;
  onSelect: (ticker: string) => void;
  onAddWatchlist: (ticker: string) => void;
  onQuickAnalyze?: (ticker: string) => void;
}

export function CandidateStockCard({
  stock,
  selected,
  watching,
  onSelect,
  onAddWatchlist,
  onQuickAnalyze,
}: CandidateStockCardProps) {
  return (
    <div
      onClick={() => onSelect(stock.ticker)}
      className={cn(
        "group relative rounded-xl p-4 cursor-pointer transition-all duration-200 border",
        selected
          ? "bg-brand/5 border-brand/30 shadow-lg shadow-brand/5"
          : "bg-surface-1 border-theme hover:bg-surface-2/50"
      )}
    >
      {/* Top row: ticker */}
      <div className="flex items-start justify-between mb-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-base font-semibold text-theme-primary">
              {stock.ticker}
            </span>
          </div>
          <p className="text-xs text-theme-muted mt-0.5">{stock.name}</p>
        </div>
        <ChevronRight
          className={cn(
            "w-4 h-4 transition-all duration-200",
            selected ? "text-brand" : "text-zinc-600 group-hover:text-zinc-400"
          )}
        />
      </div>

      {/* Reason */}
      <p className="text-xs text-theme-secondary leading-relaxed mb-3 line-clamp-2">
        {stock.reason}
      </p>

      {/* Metrics row */}
      <div className="flex items-center gap-3">
        <div className="text-xs">
          <span className="text-zinc-500">动量 </span>
          <span className="font-medium text-theme-secondary">{stock.momentum_score}</span>
        </div>
        {stock.current_price != null && (
          <div className="text-xs">
            <span className="text-zinc-500">价格 </span>
            <span className="font-medium text-theme-secondary">{stock.current_price.toFixed(2)}</span>
          </div>
        )}
        {stock.trend_r2 != null && (
          <div className="text-xs">
            <span className="text-zinc-500">R² </span>
            <span className="font-medium text-theme-secondary">{stock.trend_r2.toFixed(2)}</span>
          </div>
        )}
        {/* Action buttons */}
        <div className="ml-auto flex items-center gap-1.5">
          {onQuickAnalyze && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onQuickAnalyze(stock.ticker);
              }}
              className="flex items-center justify-center gap-1 px-2 py-1 rounded-lg text-[11px] transition-colors bg-violet-500/10 text-violet-400 hover:bg-violet-500/20"
            >
              <Zap className="w-3 h-3" />
              分析
            </button>
          )}
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (!watching) onAddWatchlist(stock.ticker);
            }}
            disabled={watching}
            className={cn(
              "flex items-center justify-center gap-1 px-2 py-1 rounded-lg text-[11px] transition-colors",
              watching
                ? "bg-amber-400/20 text-amber-400 cursor-default"
                : "bg-brand/10 text-brand hover:bg-brand/20"
            )}
          >
            {watching ? <Check className="w-3 h-3" /> : <Plus className="w-3 h-3" />}
            {watching ? "观察中" : "观察"}
          </button>
        </div>
      </div>
    </div>
  );
}
