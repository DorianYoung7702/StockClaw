"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  Bot,
  CheckCircle2,
  Eye,
  ExternalLink,
  FileText,
  Activity,
  Maximize2,
  Minimize2,
  Newspaper,
  RefreshCw,
  Sparkles,
  TrendingUp,
  TrendingDown,
  X,
  Zap,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useState, useCallback, useRef } from "react";
import { cn, cleanLLMOutput } from "@/lib/utils";
import { explainStream } from "@/lib/api";
import type { StockAnalysis, StrongStock } from "@/lib/types";
import { AnalysisSectionCard } from "./analysis-section-card";

const panelVariants = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -12 },
};
const panelTransition = { duration: 0.25, ease: "easeInOut" as const };

interface StockAnalysisPanelProps {
  analysis: StockAnalysis | null;
  loading?: boolean;
  technicalLoading?: boolean;
  toolStatus?: string | null;
  completedSteps?: string[];
  ticker?: string | null;
  selectedStock?: StrongStock | null;
  activeTab?: "technical" | "fundamental";
  onTabChange?: (tab: "technical" | "fundamental") => void;
  expanded?: boolean;
  onClose?: () => void;
  onToggleExpand?: () => void;
  onRetry?: () => void;
  onAnalyze?: () => void;
  onFetchTechnicalData?: (ticker: string) => void | Promise<void>;
  ragDocumentText?: string;
  onRagDocumentTextChange?: (value: string) => void;
}

const REC_STYLES = {
  "关注": { color: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20", icon: CheckCircle2 },
  "观察": { color: "text-amber-400 bg-amber-400/10 border-amber-400/20", icon: Eye },
  "谨慎": { color: "text-rose-400 bg-rose-400/10 border-rose-400/20", icon: AlertTriangle },
};

export function StockAnalysisPanel({
  analysis, loading, technicalLoading = false, toolStatus, completedSteps = [], ticker, selectedStock, activeTab = "technical",
  onTabChange, expanded, onClose, onToggleExpand, onRetry, onAnalyze, onFetchTechnicalData, ragDocumentText = "", onRagDocumentTextChange,
}: StockAnalysisPanelProps) {
  const hasTicker = !!ticker || !!selectedStock;
  const displayName = selectedStock?.name || ticker || "";
  const displayTicker = ticker || selectedStock?.ticker || "";
  const showFundamentalLoading = loading && activeTab === "fundamental";
  // Only treat analysis as available if it belongs to the currently selected ticker
  const currentAnalysis = analysis && analysis.ticker === displayTicker ? analysis : null;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header with tabs */}
      {hasTicker && (
        <div className="shrink-0 border-b border-theme">
          <div className="px-4 py-3 flex items-start justify-between gap-3">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-semibold text-theme-primary">{displayTicker}</h2>
                <span className="text-xs text-theme-muted">{displayName}</span>
              </div>
            </div>
            <div className="flex items-center gap-1">
              {onToggleExpand && (
                <button
                  onClick={onToggleExpand}
                  className="text-zinc-500 hover:text-zinc-300 transition-colors p-1 rounded hover:bg-surface-2"
                  title={expanded ? "收起" : "展开"}
                >
                  {expanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
                </button>
              )}
              {onClose && (
                <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300 transition-colors p-1 rounded hover:bg-surface-2">
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>
          {/* Tab switcher */}
          <div className="px-4 flex gap-1 pb-2 overflow-x-auto">
            <button
              onClick={() => onTabChange?.("technical")}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                activeTab === "technical"
                  ? "bg-brand/10 text-brand"
                  : "text-zinc-500 hover:text-zinc-300 hover:bg-surface-2"
              )}
            >
              <Activity className="w-3 h-3" />
              近期指标
            </button>
            <button
              onClick={() => {
                onTabChange?.("fundamental");
              }}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
                activeTab === "fundamental"
                  ? "bg-brand/10 text-brand"
                  : "text-zinc-500 hover:text-zinc-300 hover:bg-surface-2"
              )}
            >
              <BarChart3 className="w-3 h-3" />
              基本面
              {loading && activeTab === "fundamental" && <div className="w-2 h-2 rounded-full border border-brand border-t-transparent animate-spin" />}
            </button>
          </div>
        </div>
      )}

      {/* Content */}
      <AnimatePresence mode="wait">
        {!hasTicker ? (
          <motion.div
            key="empty"
            variants={panelVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            transition={panelTransition}
            className="flex flex-col items-center justify-center h-full text-center px-6"
          >
            <div className="w-16 h-16 rounded-2xl bg-surface-1 border border-zinc-800/50 flex items-center justify-center mb-4">
              <Eye className="w-7 h-7 text-zinc-600" />
            </div>
            <p className="text-sm text-zinc-400">选择一只候选股查看分析</p>
            <p className="text-xs text-zinc-600 mt-1">点击卡片查看近期指标，点击「基本面」查看深度分析</p>
          </motion.div>
        ) : activeTab === "technical" ? (
          <TechnicalContent
            key={`tech-${displayTicker}`}
            stock={selectedStock}
            ticker={displayTicker}
            onAnalyze={onAnalyze}
            hasAnalysis={!!currentAnalysis}
            loading={!!loading}
            technicalLoading={technicalLoading}
            onFetchTechnicalData={onFetchTechnicalData}
            onSwitchToFundamental={() => {
              onTabChange?.("fundamental");
            }}
          />
        ) : showFundamentalLoading ? (
          <motion.div
            key="loading"
            variants={panelVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            transition={panelTransition}
            className="flex flex-col h-full"
          >
            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
              {/* Current status */}
              <div className="flex items-center gap-3 rounded-xl bg-brand/5 border border-brand/10 p-4">
                <div className="w-5 h-5 rounded-full border-2 border-brand border-t-transparent animate-spin" />
                <div>
                  <p className="text-sm font-medium text-theme-primary">
                    {toolStatus || `正在分析 ${displayTicker}...`}
                  </p>
                  <p className="text-xs text-theme-muted mt-0.5">LangChain Agent 执行中，通常需要1-3 分钟</p>
                </div>
              </div>
              {/* Completed steps */}
              {completedSteps.length > 0 && (
                <div className="rounded-xl bg-surface-1 border border-zinc-800/50 p-4 space-y-2">
                  <div className="text-xs font-medium text-theme-muted mb-1">执行进度</div>
                  {completedSteps.map((step, i) => (
                    <div key={`${step}-${i}`} className="flex items-center gap-2 text-xs">
                      {i < completedSteps.length - 1 || !toolStatus ? (
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                      ) : (
                        <div className="w-3.5 h-3.5 rounded-full border-2 border-brand border-t-transparent animate-spin shrink-0" />
                      )}
                      <span className={i < completedSteps.length - 1 || !toolStatus ? "text-theme-muted" : "text-theme-primary"}>{step}</span>
                    </div>
                  ))}
                </div>
              )}
              {/* Skeleton sections */}
              {["盈利分析", "增长分析", "估值分析", "资产负债"].map((label) => (
                <div key={label} className="rounded-xl bg-surface-1 border border-zinc-800/50 p-4">
                  <div className="text-xs font-medium text-theme-muted mb-3">{label}</div>
                  <div className="h-2 bg-surface-2 rounded w-full mb-2 animate-pulse" />
                  <div className="h-2 bg-surface-2 rounded w-3/4 animate-pulse" />
                </div>
              ))}
            </div>
          </motion.div>
        ) : currentAnalysis ? (
          <AnalysisContent
            key={`analysis-${currentAnalysis.ticker}`}
            analysis={currentAnalysis}
            expanded={expanded}
            onRetry={onRetry}
          />
        ) : (
          <motion.div
            key="no-analysis"
            variants={panelVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            transition={panelTransition}
            className="flex flex-col items-center justify-center h-full text-center px-6"
          >
            <BarChart3 className="w-10 h-10 text-zinc-600 mb-3" />
            <p className="text-sm text-zinc-400">尚未进行基本面分析</p>
            <p className="text-xs text-zinc-600 mt-1 mb-4">你可以直接开始分析，或先粘贴财报 / MD&A 片段，作为本次 RAG 检索的财报切片来源。</p>
            {onRagDocumentTextChange && (
              <div className="w-full max-w-xl mb-4 text-left">
                <div className="text-[11px] text-zinc-500 mb-2">可选：粘贴 10-K、年报、MD&A、风险因素等原文片段</div>
                <textarea
                  value={ragDocumentText}
                  onChange={(e) => onRagDocumentTextChange(e.target.value)}
                  placeholder="示例：管理层讨论与分析、风险因素、业务分部描述……粘贴后将先切片写入 Chroma，再参与本次分析检索。"
                  className="w-full min-h-[120px] rounded-xl bg-surface-1 border border-zinc-800/60 px-3 py-2 text-xs text-zinc-300 placeholder:text-zinc-500 outline-none focus:border-brand/40 resize-y"
                />
              </div>
            )}
            {onAnalyze && (
              <button
                onClick={onAnalyze}
                disabled={!!loading}
                className={cn(
                  "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors border",
                  loading
                    ? "bg-zinc-800/50 text-zinc-500 border-zinc-700/30 cursor-not-allowed"
                    : "bg-brand/10 text-brand hover:bg-brand/20 border-brand/20"
                )}
              >
                {loading ? (
                  <>
                    <div className="w-4 h-4 rounded-full border-2 border-zinc-500 border-t-transparent animate-spin" />
                    分析中...
                  </>
                ) : (
                  <>
                    <BarChart3 className="w-4 h-4" />
                    开始基本面分析
                  </>
                )}
              </button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Technical Content — shows cached StrongStock data                  */
/* ------------------------------------------------------------------ */

function TechnicalContent({
  stock,
  ticker,
  onAnalyze,
  hasAnalysis,
  loading,
  technicalLoading,
  onFetchTechnicalData,
  onSwitchToFundamental,
}: {
  stock: StrongStock | null | undefined;
  ticker: string;
  onAnalyze?: () => void;
  hasAnalysis: boolean;
  loading: boolean;
  technicalLoading: boolean;
  onFetchTechnicalData?: (ticker: string) => void | Promise<void>;
  onSwitchToFundamental?: () => void;
}) {
  const [agentExplanation, setAgentExplanation] = useState<string>("");
  const [agentLoading, setAgentLoading] = useState(false);
  const explanationCacheRef = useRef<Record<string, string>>({});

  const triggerAgentExplanation = useCallback(async () => {
    if (!stock) return;
    const key = stock.ticker;

    // Return cached
    if (explanationCacheRef.current[key]) {
      setAgentExplanation(explanationCacheRef.current[key]);
      return;
    }

    setAgentLoading(true);
    setAgentExplanation("");

    const metricsBlock = [
      `动量综合评分: ${stock.momentum_score.toFixed(2)}`,
      stock.rs_20d != null ? `20日超额收益(RS): ${stock.rs_20d.toFixed(2)}%` : null,
      stock.vol_score != null ? `量比(Vol Score): ${stock.vol_score.toFixed(2)}x` : null,
      stock.trend_r2 != null ? `趋势R²: ${stock.trend_r2.toFixed(2)}` : null,
      stock.performance_20d != null ? `20日涨幅: ${stock.performance_20d.toFixed(2)}%` : null,
      stock.performance_40d != null ? `40日涨幅: ${stock.performance_40d.toFixed(2)}%` : null,
      stock.performance_90d != null ? `90日涨幅: ${stock.performance_90d.toFixed(2)}%` : null,
      stock.current_price != null ? `现价: $${stock.current_price.toFixed(2)}` : null,
      `5日均量: ${stock.avg_volume > 1e6 ? (stock.avg_volume / 1e6).toFixed(1) + "M" : (stock.avg_volume / 1e3).toFixed(0) + "K"}`,
    ].filter(Boolean).join("\n");

    const prompt = `你是一个专业的量化技术分析师。请根据以下量化指标，用简洁中文解释为什么 ${stock.ticker}（${stock.name}）被判定为强势股。

指标数据：
${metricsBlock}

评分公式说明：动量综合评分 = 相对强度(40%) + 量价配合(30%) + 趋势平滑性R²(30%)
- 相对强度(RS)：个股20日涨幅减去基准指数涨幅，衡量超额收益
- 量比(Vol Score)：近20日均量/前20日均量，>1说明放量
- 趋势R²：近20日收盘价线性回归R²，越高说明上涨越平稳

请从以下角度分析：
1. **强势核心逻辑**：这只股票为什么强？哪些指标突出？
2. **量价关系**：成交量配合情况如何？
3. **趋势质量**：上涨趋势是否稳健？
4. **潜在风险**：需要注意什么？

控制在200字以内，直接分析，不要重复数据。`;

    let text = "";
    try {
      await explainStream(prompt, (token) => {
        text += token;
        setAgentExplanation(cleanLLMOutput(text));
      });
      text = cleanLLMOutput(text);
      explanationCacheRef.current[key] = text;
      setAgentExplanation(text);
    } catch (err) {
      console.error("Agent explanation failed:", err);
      const fallback = "分析请求失败，请稍后重试。";
      setAgentExplanation(fallback);
    } finally {
      setAgentLoading(false);
    }
  }, [stock]);

  if (!stock) {
    return (
      <motion.div
        key="tech-empty"
        variants={panelVariants}
        initial="initial"
        animate="animate"
        exit="exit"
        transition={panelTransition}
        className="flex flex-col items-center justify-center h-full text-center px-6"
      >
        <Activity className="w-10 h-10 text-zinc-600 mb-3" />
        <p className="text-sm text-zinc-400">{ticker} 的近期指标尚未加载</p>
        <p className="text-xs text-zinc-600 mt-1 mb-4">点击下方按钮拉取当前市场的最新指标缓存</p>
        {onFetchTechnicalData && (
          <button
            onClick={() => onFetchTechnicalData(ticker)}
            disabled={technicalLoading}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors border",
              technicalLoading
                ? "bg-zinc-800/50 text-zinc-500 border-zinc-700/30 cursor-not-allowed"
                : "bg-brand/10 text-brand hover:bg-brand/20 border-brand/20"
            )}
          >
            {technicalLoading ? (
              <>
                <div className="w-4 h-4 rounded-full border-2 border-zinc-500 border-t-transparent animate-spin" />
                获取中...
              </>
            ) : (
              <>
                <RefreshCw className="w-4 h-4" />
                获取指标数据
              </>
            )}
          </button>
        )}
      </motion.div>
    );
  }

  const TREND_COLORS = {
    strong: "text-emerald-400",
    neutral: "text-zinc-400",
    weak: "text-rose-400",
  };
  const TREND_LABELS = { strong: "强势", neutral: "中性", weak: "弱势" };
  const RISK_LABELS = { low: "低风险", medium: "中风险", high: "高风险" };
  const RISK_COLORS = {
    low: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
    medium: "text-amber-400 bg-amber-400/10 border-amber-400/20",
    high: "text-rose-400 bg-rose-400/10 border-rose-400/20",
  };

  const msPercent = Math.min(100, Math.round(stock.momentum_score * 100));
  const msColor = msPercent > 60 ? "bg-emerald-400" : msPercent > 30 ? "bg-brand" : "bg-amber-400";

  return (
    <motion.div
      key={`tech-${stock.ticker}`}
      variants={panelVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      transition={panelTransition}
      className="flex-1 overflow-y-auto px-4 py-4 space-y-4"
    >
      {/* Overview card with reason */}
      <div className="rounded-xl bg-gradient-to-br from-surface-1 to-surface-2/50 border-theme p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-base font-semibold text-theme-primary">{stock.ticker}</span>
            <span className="text-xs text-theme-muted">{stock.name}</span>
            {stock.current_price != null && (
              <span className="text-xs font-medium text-zinc-300">${stock.current_price.toFixed(2)}</span>
            )}
          </div>
          <div className={cn(
            "inline-flex items-center gap-1 px-2 py-1 rounded-lg border text-xs font-medium",
            RISK_COLORS[stock.risk_level]
          )}>
            {RISK_LABELS[stock.risk_level]}
          </div>
        </div>
        <p className="text-xs text-theme-secondary leading-relaxed">{stock.reason}</p>
      </div>

      {/* Momentum Score Breakdown */}
      <div className="rounded-xl bg-surface-1 border border-zinc-800/50 p-4">
        <h3 className="text-sm font-medium text-zinc-200 flex items-center gap-1.5 mb-3">
          <Zap className="w-3.5 h-3.5 text-brand" />
          动量评分
        </h3>
        {/* Overall score bar */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-zinc-400">综合评分</span>
            <span className="text-xs font-semibold text-zinc-200">{stock.momentum_score.toFixed(2)}</span>
          </div>
          <div className="relative h-2 bg-surface-2 rounded-full overflow-hidden">
            <div className={cn("absolute top-0 left-0 h-full rounded-full transition-all", msColor)} style={{ width: `${msPercent}%` }} />
          </div>
        </div>
        {/* Sub-metrics */}
        <div className="space-y-2.5">
          {stock.rs_20d != null && (
            <SubMetricBar label="相对强度 (40%)" value={stock.rs_20d} displayValue={`${stock.rs_20d >= 0 ? "+" : ""}${stock.rs_20d.toFixed(1)}%`} percent={Math.min(100, Math.max(0, stock.rs_20d / 50 * 100))} color="bg-cyan-400" />
          )}
          {stock.vol_score != null && (
            <SubMetricBar label="量价配合 (30%)" value={stock.vol_score} displayValue={`${stock.vol_score.toFixed(2)}x`} percent={Math.min(100, Math.max(0, (stock.vol_score - 0.5) / 1.5 * 100))} color="bg-violet-400" />
          )}
          {stock.trend_r2 != null && (
            <SubMetricBar label="趋势平滑 R² (30%)" value={stock.trend_r2} displayValue={stock.trend_r2.toFixed(2)} percent={Math.round(stock.trend_r2 * 100)} color="bg-amber-400" />
          )}
        </div>
      </div>

      {/* Performance across periods */}
      {(stock.performance_20d != null || stock.performance_40d != null || stock.performance_90d != null) && (
        <div className="rounded-xl bg-surface-1 border border-zinc-800/50 p-4">
          <h3 className="text-sm font-medium text-zinc-200 flex items-center gap-1.5 mb-3">
            <TrendingUp className="w-3.5 h-3.5 text-brand" />
            多周期表现
          </h3>
          <div className="grid grid-cols-2 gap-3">
            {stock.performance_20d != null && <MetricItem label="20日" value={`${stock.performance_20d >= 0 ? "+" : ""}${stock.performance_20d.toFixed(1)}%`} color={stock.performance_20d > 0 ? "text-emerald-400" : "text-rose-400"} />}
            {stock.performance_40d != null && <MetricItem label="40日" value={`${stock.performance_40d >= 0 ? "+" : ""}${stock.performance_40d.toFixed(1)}%`} color={stock.performance_40d > 0 ? "text-emerald-400" : "text-rose-400"} />}
            {stock.performance_90d != null && <MetricItem label="90日" value={`${stock.performance_90d >= 0 ? "+" : ""}${stock.performance_90d.toFixed(1)}%`} color={stock.performance_90d > 0 ? "text-emerald-400" : "text-rose-400"} />}
            {stock.performance_180d != null && <MetricItem label="180日" value={`${stock.performance_180d >= 0 ? "+" : ""}${stock.performance_180d.toFixed(1)}%`} color={stock.performance_180d > 0 ? "text-emerald-400" : "text-rose-400"} />}
          </div>
        </div>
      )}

      {/* Basic technical metrics */}
      <div className="rounded-xl bg-surface-1 border border-zinc-800/50 p-4">
        <h3 className="text-sm font-medium text-zinc-200 flex items-center gap-1.5 mb-3">
          <Activity className="w-3.5 h-3.5 text-brand" />
          技术指标
        </h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <MetricItem
            label="趋势"
            value={TREND_LABELS[stock.trend]}
            color={TREND_COLORS[stock.trend]}
            icon={stock.trend === "strong" ? <TrendingUp className="w-3 h-3" /> : stock.trend === "weak" ? <TrendingDown className="w-3 h-3" /> : undefined}
          />
          <MetricItem
            label="成交量 (5日均)"
            value={stock.avg_volume > 1e6 ? `${(stock.avg_volume / 1e6).toFixed(1)}M` : stock.avg_volume > 1e3 ? `${(stock.avg_volume / 1e3).toFixed(0)}K` : String(stock.avg_volume)}
          />
          <MetricItem label="RSI" value={stock.rsi.toFixed(1)} color={stock.rsi > 60 ? "text-emerald-400" : stock.rsi < 40 ? "text-rose-400" : "text-zinc-300"} />
        </div>
      </div>

      {/* Agent Explanation Card */}
      <div className="rounded-xl bg-surface-1 border border-zinc-800/50 overflow-hidden">
        <div className="px-4 py-3 flex items-center justify-between border-b border-zinc-800/30">
          <div className="flex items-center gap-2">
            <div className="w-5 h-5 rounded-md bg-brand/15 flex items-center justify-center">
              <Bot className="w-3 h-3 text-brand" />
            </div>
            <span className="text-xs font-medium text-zinc-200">AI 强势解读</span>
          </div>
          {!agentExplanation && !agentLoading && (
            <button
              onClick={triggerAgentExplanation}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium bg-brand/10 text-brand hover:bg-brand/20 transition-colors border border-brand/20"
            >
              <Sparkles className="w-3 h-3" />
              生成解读
            </button>
          )}
        </div>
        <div className="px-4 py-3">
          {agentLoading && !agentExplanation ? (
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 rounded-full border-2 border-brand border-t-transparent animate-spin shrink-0" />
              <span className="text-xs text-zinc-400">正在分析强势原因...</span>
            </div>
          ) : agentExplanation ? (
            <div className="prose prose-sm prose-zinc dark:prose-invert max-w-none text-xs text-zinc-300 leading-relaxed">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{cleanLLMOutput(agentExplanation)}</ReactMarkdown>
              {agentLoading && <span className="inline-block w-1.5 h-3.5 bg-brand/60 animate-pulse ml-0.5 align-text-bottom rounded-sm" />}
            </div>
          ) : (
            <p className="text-xs text-zinc-500">点击「生成解读」让 AI 基于量化指标解释该股为何被判定为强势。</p>
          )}
        </div>
      </div>

      {/* CTA: go to fundamental */}
      <div className="rounded-xl bg-surface-1 border border-zinc-800/50 p-4">
        <p className="text-xs text-zinc-500 mb-3">近期指标来自强势股筛选缓存，如需更深入的财务分析：</p>
        <button
          onClick={hasAnalysis ? onSwitchToFundamental : onAnalyze}
          disabled={loading && !hasAnalysis}
          className={cn(
            "w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors border",
            loading && !hasAnalysis
              ? "bg-zinc-800/50 text-zinc-500 border-zinc-700/30 cursor-not-allowed"
              : "bg-brand/10 text-brand hover:bg-brand/20 border-brand/20"
          )}
        >
          {loading && !hasAnalysis ? (
            <>
              <div className="w-4 h-4 rounded-full border-2 border-zinc-500 border-t-transparent animate-spin" />
              分析中...
            </>
          ) : (
            <>
              <BarChart3 className="w-4 h-4" />
              {hasAnalysis ? "查看基本面分析" : "开始基本面分析"}
            </>
          )}
        </button>
      </div>
    </motion.div>
  );
}

function MetricItem({ label, value, color, icon }: { label: string; value: string; color?: string; icon?: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] text-zinc-500 mb-0.5">{label}</p>
      <p className={cn("text-sm font-semibold flex items-center gap-1", color || "text-zinc-200")}>
        {icon}
        {value}
      </p>
    </div>
  );
}

function SubMetricBar({ label, displayValue, percent, color }: { label: string; value: number; displayValue: string; percent: number; color: string }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-0.5">
        <span className="text-[10px] text-zinc-500">{label}</span>
        <span className="text-[10px] font-medium text-zinc-300">{displayValue}</span>
      </div>
      <div className="relative h-1.5 bg-surface-2 rounded-full overflow-hidden">
        <div className={cn("absolute top-0 left-0 h-full rounded-full transition-all", color)} style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} />
      </div>
    </div>
  );
}

function AnalysisContent({
  analysis,
  expanded,
  onRetry,
}: {
  analysis: StockAnalysis;
  expanded?: boolean;
  onRetry?: () => void;
}) {
  const rec = REC_STYLES[analysis.recommendation] || REC_STYLES["观察"];
  const RecIcon = rec.icon;
  const evidenceChain = analysis.evidence_chain || [];
  const retrievalDebug = analysis.retrieval_debug || {};
  const filingCount = evidenceChain.filter((item) => item.source_type === "filing").length;
  const newsCount = evidenceChain.filter((item) => item.source_type === "news").length;

  return (
    <motion.div
      variants={panelVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      transition={panelTransition}
      className="flex-1 overflow-y-auto"
    >
      <div className="px-4 py-4 space-y-4">
        {/* Overview card */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.05 }}
          className="rounded-xl bg-gradient-to-br from-surface-1 to-surface-2/50 border-theme p-4"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between mb-3">
            <div className="flex-1 prose prose-sm prose-zinc dark:prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{cleanLLMOutput(analysis.conclusion)}</ReactMarkdown>
            </div>
            <div
              className={cn(
                "shrink-0 inline-flex items-center gap-1 self-start px-2 py-1 rounded-lg border text-xs font-medium",
                rec.color
              )}
            >
              <RecIcon className="w-3 h-3" />
              {analysis.recommendation}
            </div>
          </div>
        </motion.div>

        {/* Analysis sections */}
        {analysis.sections.map((section, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.08 * (i + 1) }}
          >
            <AnalysisSectionCard section={section} defaultOpen={i === 0} />
          </motion.div>
        ))}

        {(evidenceChain.length > 0 || Object.keys(retrievalDebug).length > 0) && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.08 * (analysis.sections.length + 1) }}
            className="rounded-xl bg-surface-1 border border-zinc-800/50 p-4 space-y-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-medium text-zinc-200 flex items-center gap-1.5 mb-1">
                  <Bot className="w-3.5 h-3.5 text-brand" />
                  RAG 证据链
                </h3>
                <p className="text-xs text-zinc-500 leading-relaxed">
                  财报切片负责补充长期基本面叙事，新闻事件负责补充近期催化、风险与市场情绪，使 Fundamental / News Agent 的结论可追溯。
                </p>
              </div>
              <div className="shrink-0 flex flex-wrap items-center gap-2 text-[11px] justify-start sm:justify-end">
                <span className="px-2 py-1 rounded-lg bg-brand/10 text-brand">证据 {evidenceChain.length}</span>
                <span className="px-2 py-1 rounded-lg bg-cyan-500/10 text-cyan-300">财报 {filingCount}</span>
                <span className="px-2 py-1 rounded-lg bg-amber-500/10 text-amber-300">新闻 {newsCount}</span>
              </div>
            </div>

            {Object.entries(retrievalDebug).length > 0 && (
              <div className="grid gap-2 md:grid-cols-2">
                {Object.entries(retrievalDebug).map(([key, debug]) => {
                  const info = debug || {};
                  const distribution = info.source_distribution || {};
                  return (
                    <div key={key} className="rounded-lg bg-surface-2/60 border border-zinc-800/40 p-3">
                      <div className="flex items-center justify-between gap-2 mb-2">
                        <span className="text-xs font-medium text-zinc-200 uppercase tracking-wide">{key}</span>
                        <span className="text-[11px] text-zinc-500">{info.status || "unknown"}</span>
                      </div>
                      <div className="space-y-1 text-[11px] text-zinc-400">
                        {info.effective_query || info.query ? <div>Query: <span className="text-zinc-300">{String(info.effective_query || info.query)}</span></div> : null}
                        {info.hit_count != null ? <div>命中数: <span className="text-zinc-300">{String(info.hit_count)}</span></div> : null}
                        {info.top_k != null ? <div>Top K: <span className="text-zinc-300">{String(info.top_k)}</span></div> : null}
                        {info.raw_item_count != null ? <div>原始新闻数: <span className="text-zinc-300">{String(info.raw_item_count)}</span></div> : null}
                        {Object.keys(distribution).length > 0 ? (
                          <div className="flex flex-wrap gap-1 pt-1">
                            {Object.entries(distribution).map(([label, count]) => (
                              <span key={`${key}-${label}`} className="px-1.5 py-0.5 rounded bg-zinc-800/80 text-zinc-300">
                                {label} {String(count)}
                              </span>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {evidenceChain.length > 0 && (
              <div className="space-y-3">
                {evidenceChain.map((item) => {
                  const isNews = item.source_type === "news";
                  return (
                    <div key={item.id} className="rounded-lg border border-zinc-800/40 bg-surface-2/40 p-3">
                      <div className="flex items-start justify-between gap-3 mb-2">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 mb-1 flex-wrap">
                            <span className={cn(
                              "inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium",
                              isNews ? "bg-amber-500/10 text-amber-300" : "bg-cyan-500/10 text-cyan-300"
                            )}>
                              {isNews ? <Newspaper className="w-3 h-3" /> : <FileText className="w-3 h-3" />}
                              {isNews ? "新闻事件" : "财报切片"}
                            </span>
                            <span className="text-[11px] text-zinc-500">{item.source_label}</span>
                            {item.score != null && <span className="text-[11px] text-brand">score {item.score.toFixed(3)}</span>}
                          </div>
                          <div className="text-sm font-medium text-zinc-100 break-words">{item.title}</div>
                        </div>
                        {item.url && (
                          <a
                            href={item.url}
                            target="_blank"
                            rel="noreferrer"
                            className="shrink-0 inline-flex items-center gap-1 text-[11px] text-brand hover:text-brand/80 transition-colors"
                          >
                            链接
                            <ExternalLink className="w-3 h-3" />
                          </a>
                        )}
                      </div>
                      <p className="text-xs text-zinc-300 leading-relaxed">{item.snippet}</p>
                      <div className="flex items-center gap-3 mt-2 text-[11px] text-zinc-500 flex-wrap">
                        {item.ticker ? <span>{item.ticker}</span> : null}
                        {item.published_at ? <span>{item.published_at}</span> : null}
                        {item.doc_label ? <span>{item.doc_label}</span> : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </motion.div>
        )}

        {/* Peer comparison */}
        {analysis.peers.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.08 * (analysis.sections.length + 1) }}
            className="rounded-xl bg-surface-1 border border-zinc-800/50 p-4"
          >
            <h3 className="text-sm font-medium text-zinc-200 mb-3">同业对比</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-zinc-800/50">
                    <th className="text-left text-zinc-500 font-normal py-2 pr-3">标的</th>
                    <th className="text-right text-zinc-500 font-normal py-2 px-2">P/E</th>
                    <th className="text-right text-zinc-500 font-normal py-2 px-2">P/B</th>
                    <th className="text-right text-zinc-500 font-normal py-2 px-2">ROE%</th>
                    <th className="text-right text-zinc-500 font-normal py-2 pl-2">市值</th>
                  </tr>
                </thead>
                <tbody>
                  {analysis.peers.map((peer) => (
                    <tr
                      key={peer.ticker}
                      className={cn(
                        "border-b border-zinc-800/30",
                        peer.ticker === analysis.ticker && "bg-brand/5"
                      )}
                    >
                      <td className="py-2 pr-3">
                        <span className="font-medium text-zinc-200">{peer.ticker}</span>
                        <span className="text-zinc-500 ml-1">{peer.name}</span>
                      </td>
                      <td className="text-right py-2 px-2 text-zinc-300">
                        {peer.pe > 0 ? peer.pe.toFixed(1) : "N/A"}
                      </td>
                      <td className="text-right py-2 px-2 text-zinc-300">{peer.pb.toFixed(1)}</td>
                      <td
                        className={cn(
                          "text-right py-2 px-2",
                          peer.roe > 0 ? "text-emerald-400" : "text-rose-400"
                        )}
                      >
                        {peer.roe.toFixed(1)}
                      </td>
                      <td className="text-right py-2 pl-2 text-zinc-300">{peer.market_cap}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </motion.div>
        )}

        {/* Retry button for error states */}
        {analysis.recommendation === "谨慎" && onRetry && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.08 * (analysis.sections.length + 1) }}
          >
            <button
              onClick={onRetry}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-brand/10 text-brand text-sm font-medium hover:bg-brand/20 transition-colors border border-brand/20"
            >
              <RefreshCw className="w-4 h-4" />
              重新分析
            </button>
          </motion.div>
        )}

        {/* Data limitations (non-fatal warnings) */}
        {analysis.risks.length > 0 && analysis.recommendation !== "谨慎" && analysis.risks.some(r => r.includes("缺失") || r.includes("限流") || r.includes("data")) && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.08 * (analysis.sections.length + 1) }}
            className="rounded-xl bg-amber-500/5 border border-amber-500/10 p-4"
          >
            <h3 className="text-sm font-medium text-amber-400 flex items-center gap-1.5 mb-2">
              <AlertTriangle className="w-3.5 h-3.5" />
              数据说明
            </h3>
            <ul className="space-y-1">
              {analysis.risks.filter(r => r.includes("缺失") || r.includes("限流") || r.includes("data")).map((r, i) => (
                <li key={`warn-${i}`} className="text-xs text-amber-400/80">· {r}</li>
              ))}
            </ul>
            {onRetry && (
              <button
                onClick={onRetry}
                className="mt-3 flex items-center gap-1.5 text-xs text-amber-400 hover:text-amber-300 transition-colors"
              >
                <RefreshCw className="w-3 h-3" />
                重新获取数据
              </button>
            )}
          </motion.div>
        )}

        {/* Risks */}
        {analysis.risks.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.08 * (analysis.sections.length + 2) }}
            className="rounded-xl bg-rose-500/5 border border-rose-500/10 p-4"
          >
            <h3 className="text-sm font-medium text-rose-400 flex items-center gap-1.5 mb-3">
              <AlertTriangle className="w-3.5 h-3.5" />
              风险提示
            </h3>
            <ul className="space-y-1.5">
              {analysis.risks.map((risk, i) => (
                <li key={i} className="flex items-start gap-2 text-xs text-zinc-400">
                  <span className="w-1 h-1 rounded-full bg-rose-400/60 mt-1.5 shrink-0" />
                  <span className="prose prose-xs prose-zinc dark:prose-invert max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{cleanLLMOutput(risk)}</ReactMarkdown>
                  </span>
                </li>
              ))}
            </ul>
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}
