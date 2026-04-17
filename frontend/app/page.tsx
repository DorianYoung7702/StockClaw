"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { ChatPanel } from "@/components/chat/chat-panel";
import { CandidateList } from "@/components/candidates/candidate-list";
import { StockAnalysisPanel } from "@/components/analysis/stock-analysis-panel";
import { useHelpCenter } from "@/components/layout/help-center";
import { useAuth } from "@/components/layout/token-gate";
import { fetchStrongStocks, fetchSingleStrongStock, analyzeStream, addToWatchlist } from "@/lib/api";
import { mapStructuredToAnalysis } from "@/lib/analysis-utils";
import { MOCK_CANDIDATES } from "@/lib/mock-data";
import type { StrongStock, StockAnalysis } from "@/lib/types";
import { useWorkbench } from "@/lib/workbench-context";
import { cn } from "@/lib/utils";
import { useUserId } from "@/lib/use-user-id";

function configCacheKey(cfg: { market_type: string; top_count: number; rsi_threshold: number; sort_by: string; min_volume_turnover?: number }) {
  return `${cfg.market_type}|${cfg.top_count}|${cfg.rsi_threshold}|${cfg.sort_by}|${cfg.min_volume_turnover ?? ""}`;
}

export default function WorkbenchPage() {
  const USER_ID = useUserId();
  const wb = useWorkbench();
  const { openHelp, hasAutoOpenedHomeGuide, markAutoOpenedHomeGuide } = useHelpCenter();
  const { hasUnlocked, beamKey } = useAuth();
  const {
    candidates, setCandidates,
    candidatesByMarket, setCandidatesForMarket,
    candidatesLoading, setCandidatesLoading,
    conditionSummary, setConditionSummary,
    selectedTicker, setSelectedTicker,
    analysisCache, setAnalysisForTicker, clearAnalysisForTicker,
    analysisLoadingTickers, setTickerAnalysisLoading,
    config,
    lastFetchKey, setLastFetchKey,
    watchedTickers, setWatchedTickers,
    setMessages,
    pushAgentMessage, setHasUnreadChat,
  } = wb;

  // Clear unread badge when user is on this page
  const pathname = usePathname();
  useEffect(() => {
    if (pathname === "/") setHasUnreadChat(false);
  }, [pathname, setHasUnreadChat]);

  const [isMobile, setIsMobile] = useState(false);
  const [mobilePanel, setMobilePanel] = useState<"chat" | "candidates" | "analysis">("chat");

  useEffect(() => {
    const media = window.matchMedia("(max-width: 767px)");
    const sync = () => setIsMobile(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    if (pathname !== "/") return;
    if (hasAutoOpenedHomeGuide) return;

    const delayMs = hasUnlocked && beamKey > 0 ? 2900 : 900;
    const timer = window.setTimeout(() => {
      openHelp();
      markAutoOpenedHomeGuide();
    }, delayMs);

    return () => window.clearTimeout(timer);
  }, [pathname, hasAutoOpenedHomeGuide, hasUnlocked, beamKey, openHelp, markAutoOpenedHomeGuide]);

  const [analysisExpanded, setAnalysisExpanded] = useState(false);
  const [chatExpanded, setChatExpanded] = useState(false);
  const fetchLockRef = useRef(false);
  const [activeAnalysisTab, setActiveAnalysisTab] = useState<"technical" | "fundamental">("technical");
  const [analysisToolStatus, setAnalysisToolStatus] = useState<string | null>(null);
  const [analysisSteps, setAnalysisSteps] = useState<string[]>([]);
  const [ragDocumentDrafts, setRagDocumentDrafts] = useState<Record<string, string>>({});

  // Map raw API response to StrongStock[]
  const mapStocks = useCallback((res: { market_type: string; stocks: Record<string, unknown>[] }): StrongStock[] => {
    return (res.stocks || []).map((s: Record<string, unknown>) => ({
      ticker: String(s.ticker || s.symbol || ""),
      name: String(s.name || s.ticker || ""),
      reason: String(s.reason || s.momentum_label || "强势股"),
      rsi: Number(s.rsi_20 ?? s.rsi ?? 50),
      momentum_score: Number(s.momentum_score ?? s.score ?? 0),
      avg_volume: Number(s.avg_volume ?? s.volume_5d_avg ?? 0),
      risk_level: String(s.risk_level || "medium") as StrongStock["risk_level"],
      trend: String(s.trend || (Number(s.momentum_score ?? 0) > 0.5 ? "strong" : Number(s.momentum_score ?? 0) > 0.3 ? "neutral" : "weak")) as StrongStock["trend"],
      market_type: res.market_type,
      rs_20d: s.rs_20d != null ? Number(s.rs_20d) : undefined,
      vol_score: s.vol_score != null ? Number(s.vol_score) : undefined,
      trend_r2: s.trend_r2 != null ? Number(s.trend_r2) : undefined,
      performance_20d: s.performance_20d != null ? Number(s.performance_20d) : undefined,
      performance_40d: s.performance_40d != null ? Number(s.performance_40d) : undefined,
      performance_90d: s.performance_90d != null ? Number(s.performance_90d) : undefined,
      performance_180d: s.performance_180d != null ? Number(s.performance_180d) : undefined,
      current_price: s.current_price != null ? Number(s.current_price) : undefined,
    }));
  }, []);

  const mapSingleStock = useCallback((s: Record<string, unknown>, marketType: StrongStock["market_type"]): StrongStock => {
    const momentumScore = Number(s.momentum_score ?? s.score ?? 0);
    const rs20d = s.rs_20d != null ? Number(s.rs_20d) : undefined;
    const trendR2 = s.trend_r2 != null ? Number(s.trend_r2) : undefined;
    return {
      ticker: String(s.ticker || s.symbol || ""),
      name: String(s.name || s.ticker || s.symbol || ""),
      reason: String(s.reason || s.momentum_label || "强势股"),
      rsi: Number(s.rsi_20 ?? s.rsi ?? 50),
      momentum_score: momentumScore,
      avg_volume: Number(s.avg_volume ?? s.volume_5d_avg ?? 0),
      risk_level: momentumScore > 0.75 ? "low" : momentumScore > 0.45 ? "medium" : "high",
      trend: trendR2 != null
        ? (trendR2 > 0.7 ? "strong" : trendR2 > 0.35 ? "neutral" : "weak")
        : (rs20d != null ? (rs20d > 0 ? "strong" : rs20d > -5 ? "neutral" : "weak") : "neutral"),
      market_type: marketType,
      rs_20d: rs20d,
      vol_score: s.vol_score != null ? Number(s.vol_score) : undefined,
      trend_r2: trendR2,
      performance_20d: s.performance_20d != null ? Number(s.performance_20d) : undefined,
      performance_40d: s.performance_40d != null ? Number(s.performance_40d) : undefined,
      performance_90d: s.performance_90d != null ? Number(s.performance_90d) : undefined,
      performance_180d: s.performance_180d != null ? Number(s.performance_180d) : undefined,
      current_price: s.current_price != null ? Number(s.current_price) : undefined,
    };
  }, []);

  const upsertCandidate = useCallback((list: StrongStock[], stock: StrongStock): StrongStock[] => {
    const next = [...list];
    const idx = next.findIndex((item) => item.ticker === stock.ticker);
    if (idx >= 0) next[idx] = stock;
    else next.unshift(stock);
    return next;
  }, []);

  const loadStrongStocks = useCallback(async (force = false) => {
    const key = configCacheKey(config);
    const market = config.market_type;

    // If we have a per-market cache hit and not forced, just restore it
    if (!force && candidatesByMarket[market]?.length > 0) {
      setCandidates(candidatesByMarket[market]);
      const mkt = market === "us_stock" ? "美股" : market === "hk_stock" ? "港股" : "ETF";
      setConditionSummary(`${mkt} · ${candidatesByMarket[market].length}只 · RSI>${config.rsi_threshold}`);
      setLastFetchKey(key);
      return;
    }

    // Skip if same fetch key and current list is non-empty
    if (!force && key === lastFetchKey && candidates.length > 0) return;
    // Prevent concurrent fetches
    if (fetchLockRef.current) return;
    fetchLockRef.current = true;

    setCandidatesLoading(true);
    try {
      const res = await fetchStrongStocks({
        market_type: market,
        top_count: config.top_count,
        rsi_threshold: config.rsi_threshold,
        sort_by: config.sort_by,
        min_volume_turnover: config.min_volume_turnover,
      });
      const stocks = mapStocks(res);
      setCandidates(stocks);
      setCandidatesForMarket(market, stocks);
      setLastFetchKey(key);
      const mkt = market === "us_stock" ? "美股" : market === "hk_stock" ? "港股" : "ETF";
      setConditionSummary(`${mkt} · ${stocks.length}只 · RSI>${config.rsi_threshold}`);
    } catch (err) {
      console.error("Failed to load strong stocks:", err);
      if (candidates.length === 0) {
        setCandidates(MOCK_CANDIDATES);
        setConditionSummary("加载失败，显示示例数据");
      }
    } finally {
      setCandidatesLoading(false);
      fetchLockRef.current = false;
    }
  }, [config, lastFetchKey, candidates.length, candidatesByMarket, setCandidates, setCandidatesForMarket, setCandidatesLoading, setConditionSummary, setLastFetchKey, mapStocks]);

  // Keep the panel on the current tab when analysis finishes — do NOT
  // auto-switch away from 近期指标 (technical).  The user can manually
  // click the 基本面 tab if they want to see the full report.

  // No auto-fetch on mount — wait for user to trigger via chat or "应用配置"

  // Lightweight select: just show technical data from cache, no API call
  const handleSelectStock = (ticker: string) => {
    if (ticker === selectedTicker) return;
    setSelectedTicker(ticker);
    setActiveAnalysisTab("technical");
    if (isMobile) setMobilePanel("analysis");
  };

  // Background analysis: runs API without changing view
  const runAnalysis = useCallback(async (ticker: string, force = false, notifyChat = false, deepDocumentText?: string) => {
    // Skip if already cached or already loading (unless forced)
    if (!force && (analysisCache[ticker] || analysisLoadingTickers.has(ticker))) return;
    setTickerAnalysisLoading(ticker, true);
    setAnalysisToolStatus(null);
    setAnalysisSteps([]);

    // Dispatch message — inform which agents are starting
    if (notifyChat) {
      pushAgentMessage(
        `🔄 **${ticker}** 深度分析已启动\n` +
        `• 📊 基本面 Agent — 获取财务数据\n` +
        `• 📰 舆情 Agent — 分析市场情绪\n` +
        `• 📝 综合 Agent — 生成分析报告`
      );
    }
    try {
      const res = await analyzeStream(ticker, undefined, {
        onStepStart: (node) => {
          const labels: Record<string, string> = {
            gather_data: "正在获取财务数据",
            sentiment: "正在分析市场情绪",
            synthesis: "正在生成分析报告",
            render_output: "正在渲染报告",
          };
          const label = labels[node] || node;
          setAnalysisToolStatus(`${label}...`);
          setAnalysisSteps((prev) => prev.includes(label) ? prev : [...prev, label]);
        },
        onStepEnd: () => setAnalysisToolStatus(null),
        onToolStart: (tool) => {
          const toolLabels: Record<string, string> = {
            get_company_profile: "获取公司概况",
            get_key_metrics: "获取核心指标",
            get_financial_statements: "获取财务报表",
            get_peer_comparison: "同业对比分析",
            get_risk_metrics: "获取风险指标",
            get_catalysts: "获取催化剂信息",
            get_company_news: "获取公司新闻",
            get_policy_events: "获取政策事件",
            web_search: "搜索补充信息",
            get_strong_stocks: "获取强势股数据",
          };
          const label = toolLabels[tool] || tool;
          setAnalysisToolStatus(`${label}...`);
          setAnalysisSteps((prev) => prev.includes(label) ? prev : [...prev, label]);
        },
        onToolEnd: () => setAnalysisToolStatus(null),
      }, deepDocumentText?.trim() || undefined);
      const analysis = mapStructuredToAnalysis(
        res.ticker,
        res.structured,
        res.report,
        res.errors,
        res.evidence_chain,
        res.retrieval_debug,
      );
      setAnalysisForTicker(res.ticker, analysis);
      if (notifyChat) {
        pushAgentMessage(`✅ **${ticker}** 深度分析完成，可在右侧面板「基本面」选项卡查看。`);
      }
    } catch (err) {
      console.error("Failed to analyze:", err);
      const isTimeout = err instanceof DOMException && err.name === "AbortError";
      const errMsg = isTimeout
        ? "分析请求超时，后端可能正在处理大量数据，请稍后重试"
        : err instanceof Error
          ? err.message
          : "未知错误";
      if (notifyChat) {
        pushAgentMessage(`⚠️ **${ticker}** 分析遇到问题：${errMsg}`);
      }
      setAnalysisForTicker(ticker, {
        ticker,
        name: ticker,
        conclusion: `深度分析加载失败: ${errMsg}`,
        recommendation: "谨慎",
        sections: [
          {
            title: "错误信息",
            score: 0,
            summary: isTimeout
              ? "LangChain 分析图执行时间较长（通常 2-4 分钟），请确认后端服务正常运行后重试。"
              : `请确认 langchain_agent 服务已启动 (uvicorn app.main:app --port 8000)。错误: ${errMsg}`,
            details: [
              "确认后端运行: http://localhost:8000/api/v1/health",
              "确认 LLM API Key 已配置 (MINIMAX_API_KEY / DEEPSEEK_API_KEY)",
              "查看后端日志获取详细错误信息",
            ],
          },
        ],
        peers: [],
        risks: [],
        evidence_chain: [],
        retrieval_debug: {},
        updated_at: new Date().toISOString(),
      });
    } finally {
      setTickerAnalysisLoading(ticker, false);
      setAnalysisToolStatus(null);
    }
  }, [analysisCache, analysisLoadingTickers, setAnalysisForTicker, setTickerAnalysisLoading, setMessages, pushAgentMessage]);

  // Trigger analysis AND switch view to the analysis card
  const handleAnalyzeStock = useCallback(async (ticker: string, notifyChat = false) => {
    setSelectedTicker(ticker);
    setActiveAnalysisTab("fundamental");
    if (isMobile) setMobilePanel("analysis");
    runAnalysis(ticker, false, notifyChat);
  }, [isMobile, runAnalysis, setSelectedTicker]);

  // Find the selected stock object for technical data display
  const selectedStock = candidates.find((s) => s.ticker === selectedTicker) || null;

  const handleAddWatchlist = async (ticker: string) => {
    // Optimistic update
    setWatchedTickers((prev) => new Set(prev).add(ticker));
    try {
      await addToWatchlist(USER_ID, ticker);
    } catch (err) {
      console.error("Failed to add to watchlist:", err);
      // Revert on failure
      setWatchedTickers((prev) => {
        const next = new Set(prev);
        next.delete(ticker);
        return next;
      });
    }
  };

  const handleFetchSingleTechnicalData = useCallback(async (ticker: string) => {
    setCandidatesLoading(true);
    try {
      const res = await fetchSingleStrongStock({
        ticker,
        market_type: config.market_type,
      });
      const stock = mapSingleStock(res.stock, config.market_type);
      const nextCandidates = upsertCandidate(candidates, stock);
      setCandidates(nextCandidates);
      const currentMarketCandidates = candidatesByMarket[config.market_type] ?? candidates;
      setCandidatesForMarket(config.market_type, upsertCandidate(currentMarketCandidates, stock));
      setSelectedTicker(stock.ticker);
    } catch (err) {
      console.error(`Failed to load recent metrics for ${ticker}:`, err);
    } finally {
      setCandidatesLoading(false);
    }
  }, [config.market_type, mapSingleStock, upsertCandidate, setCandidates, setCandidatesForMarket, setCandidatesLoading, setSelectedTicker, candidatesByMarket, candidates]);

  // Called when user clicks "应用配置并获取强势股" — populate candidates from fetched data
  const handleConfigApply = useCallback((rawStocks: Record<string, unknown>[]) => {
    const stocks: StrongStock[] = rawStocks.map((s) => ({
      ticker: String(s.ticker || s.symbol || ""),
      name: String(s.name || s.ticker || ""),
      reason: String(s.reason || s.momentum_label || "强势股"),
      rsi: Number(s.rsi_20 ?? s.rsi ?? 50),
      momentum_score: Number(s.momentum_score ?? s.score ?? 0),
      avg_volume: Number(s.avg_volume ?? s.volume_5d_avg ?? 0),
      risk_level: String(s.risk_level || "medium") as StrongStock["risk_level"],
      trend: String(s.trend || (Number(s.momentum_score ?? 0) > 0.5 ? "strong" : Number(s.momentum_score ?? 0) > 0.3 ? "neutral" : "weak")) as StrongStock["trend"],
      market_type: config.market_type,
      rs_20d: s.rs_20d != null ? Number(s.rs_20d) : undefined,
      vol_score: s.vol_score != null ? Number(s.vol_score) : undefined,
      trend_r2: s.trend_r2 != null ? Number(s.trend_r2) : undefined,
      performance_20d: s.performance_20d != null ? Number(s.performance_20d) : undefined,
      performance_40d: s.performance_40d != null ? Number(s.performance_40d) : undefined,
      performance_90d: s.performance_90d != null ? Number(s.performance_90d) : undefined,
      performance_180d: s.performance_180d != null ? Number(s.performance_180d) : undefined,
      current_price: s.current_price != null ? Number(s.current_price) : undefined,
    }));
    setCandidates(stocks);
    setCandidatesForMarket(config.market_type, stocks);
    setLastFetchKey(configCacheKey(config));
    const mkt = config.market_type === "us_stock" ? "美股" : config.market_type === "hk_stock" ? "港股" : "ETF";
    setConditionSummary(`${mkt} · ${stocks.length}只 · RSI>${config.rsi_threshold}`);
  }, [config, setCandidates, setCandidatesForMarket, setLastFetchKey, setConditionSummary]);

  // Chat responses no longer auto-refresh candidate list to avoid
  // invalidating caches. Users explicitly click "应用配置" to refresh.
  const handleChatResponse = useCallback((_text: string) => {
    // intentionally empty — chat should not trigger side effects on other panels
  }, []);

  // Switch market from candidate list tabs
  const handleMarketChange = useCallback((market: string) => {
    // Save current candidates to per-market cache before switching
    if (candidates.length > 0) {
      setCandidatesForMarket(config.market_type, candidates);
    }
    wb.setConfig((prev) => ({ ...prev, market_type: market as typeof prev.market_type }));
    // Restore from per-market cache immediately if available
    const cached = candidatesByMarket[market];
    if (cached && cached.length > 0) {
      setCandidates(cached);
      const mkt = market === "us_stock" ? "美股" : market === "hk_stock" ? "港股" : "ETF";
      setConditionSummary(`${mkt} · ${cached.length}只 · RSI>${config.rsi_threshold}`);
    } else {
      // No cache — clear list and let user trigger fetch
      setCandidates([]);
      const mkt = market === "us_stock" ? "美股" : market === "hk_stock" ? "港股" : "ETF";
      setConditionSummary(`${mkt} · 请获取强势股数据`);
    }
  }, [wb, config, candidates, candidatesByMarket, setCandidates, setCandidatesForMarket, setConditionSummary]);


  return (
    <div className="h-full flex flex-col overflow-hidden">
      {isMobile ? (
        <>
          <div className="shrink-0 border-b border-theme px-3 py-2 flex items-center gap-2 overflow-x-auto">
            <button
              onClick={() => setMobilePanel("chat")}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors",
                mobilePanel === "chat" ? "bg-brand/10 text-brand" : "text-zinc-500 hover:text-zinc-300 hover:bg-surface-2"
              )}
            >
              对话
            </button>
            <button
              onClick={() => setMobilePanel("candidates")}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors",
                mobilePanel === "candidates" ? "bg-brand/10 text-brand" : "text-zinc-500 hover:text-zinc-300 hover:bg-surface-2"
              )}
            >
              候选股
            </button>
            <button
              onClick={() => setMobilePanel("analysis")}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors",
                mobilePanel === "analysis" ? "bg-brand/10 text-brand" : "text-zinc-500 hover:text-zinc-300 hover:bg-surface-2"
              )}
            >
              分析{selectedTicker ? ` · ${selectedTicker}` : ""}
            </button>
          </div>

          <div className="flex-1 min-h-0 overflow-hidden">
            {mobilePanel === "chat" ? (
              <div className="h-full flex flex-col overflow-hidden">
                <ChatPanel
                  onConfigApply={handleConfigApply}
                  onChatResponse={handleChatResponse}
                  onAnalyzeStock={(ticker) => handleAnalyzeStock(ticker, true)}
                  expanded
                  onToggleExpand={() => setChatExpanded((v) => !v)}
                />
              </div>
            ) : mobilePanel === "candidates" ? (
              <div className="h-full flex flex-col overflow-hidden">
                <CandidateList
                  stocks={candidates}
                  selectedTicker={selectedTicker}
                  watchedTickers={watchedTickers}
                  onSelect={handleSelectStock}
                  onAddWatchlist={handleAddWatchlist}
                  onQuickAnalyze={(ticker) => {
                    setSelectedTicker(ticker);
                    setActiveAnalysisTab("fundamental");
                    setMobilePanel("analysis");
                    runAnalysis(ticker, false, true);
                  }}
                  loading={candidatesLoading}
                  conditionSummary={conditionSummary}
                  activeMarket={config.market_type}
                  onMarketChange={handleMarketChange}
                  onRefresh={() => loadStrongStocks(true)}
                />
              </div>
            ) : (
              <div className="h-full flex flex-col overflow-hidden">
                <StockAnalysisPanel
                  analysis={selectedTicker ? analysisCache[selectedTicker] ?? null : null}
                  loading={selectedTicker ? analysisLoadingTickers.has(selectedTicker) : false}
                  technicalLoading={candidatesLoading}
                  toolStatus={analysisToolStatus}
                  completedSteps={analysisSteps}
                  ticker={selectedTicker}
                  selectedStock={selectedStock}
                  activeTab={activeAnalysisTab}
                  onTabChange={setActiveAnalysisTab}
                  expanded={analysisExpanded}
                  onToggleExpand={() => setAnalysisExpanded((v) => !v)}
                  onClose={() => {
                    setAnalysisExpanded(false);
                    setSelectedTicker(null);
                    setActiveAnalysisTab("technical");
                    setMobilePanel("candidates");
                  }}
                  onRetry={() => {
                    if (selectedTicker) {
                      clearAnalysisForTicker(selectedTicker);
                      runAnalysis(selectedTicker, true, false, ragDocumentDrafts[selectedTicker]);
                    }
                  }}
                  onAnalyze={() => {
                    if (selectedTicker) runAnalysis(selectedTicker, false, false, ragDocumentDrafts[selectedTicker]);
                  }}
                  onFetchTechnicalData={(ticker) => {
                    void handleFetchSingleTechnicalData(ticker);
                  }}
                  ragDocumentText={selectedTicker ? (ragDocumentDrafts[selectedTicker] ?? "") : ""}
                  onRagDocumentTextChange={(value: string) => {
                    if (!selectedTicker) return;
                    setRagDocumentDrafts((prev) => ({ ...prev, [selectedTicker]: value }));
                  }}
                />
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="flex-1 flex overflow-hidden">
          <AnimatePresence initial={false}>
            {!analysisExpanded && (
              <motion.div
                key="chat-panel"
                initial={{ width: 0, opacity: 0 }}
                animate={{ width: chatExpanded ? "100%" : 800, opacity: 1 }}
                exit={{ width: 0, opacity: 0 }}
                transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
                className="shrink-0 border-r border-theme flex flex-col overflow-hidden"
              >
                <ChatPanel
                  onConfigApply={handleConfigApply}
                  onChatResponse={handleChatResponse}
                  onAnalyzeStock={(ticker) => handleAnalyzeStock(ticker, true)}
                  expanded={chatExpanded}
                  onToggleExpand={() => setChatExpanded((v) => !v)}
                />
              </motion.div>
            )}
          </AnimatePresence>

          <AnimatePresence initial={false}>
            {!analysisExpanded && (
              <motion.div
                key="candidate-panel"
                initial={{ flex: 0, opacity: 0 }}
                animate={{ flex: 1, opacity: 1 }}
                exit={{ flex: 0, opacity: 0 }}
                transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
                className="min-w-0 border-r border-theme flex flex-col overflow-hidden"
              >
                <CandidateList
                  stocks={candidates}
                  selectedTicker={selectedTicker}
                  watchedTickers={watchedTickers}
                  onSelect={handleSelectStock}
                  onAddWatchlist={handleAddWatchlist}
                  onQuickAnalyze={(ticker) => {
                    setSelectedTicker(ticker);
                    setActiveAnalysisTab("fundamental");
                    runAnalysis(ticker, false, true);
                  }}
                  loading={candidatesLoading}
                  conditionSummary={conditionSummary}
                  activeMarket={config.market_type}
                  onMarketChange={handleMarketChange}
                  onRefresh={() => loadStrongStocks(true)}
                />
              </motion.div>
            )}
          </AnimatePresence>

          <motion.div
            layout
            transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
            className={analysisExpanded ? "flex-1 flex flex-col" : "flex-1 min-w-0 flex flex-col"}
          >
            <StockAnalysisPanel
              analysis={selectedTicker ? analysisCache[selectedTicker] ?? null : null}
              loading={selectedTicker ? analysisLoadingTickers.has(selectedTicker) : false}
              technicalLoading={candidatesLoading}
              toolStatus={analysisToolStatus}
              completedSteps={analysisSteps}
              ticker={selectedTicker}
              selectedStock={selectedStock}
              activeTab={activeAnalysisTab}
              onTabChange={setActiveAnalysisTab}
              expanded={analysisExpanded}
              onToggleExpand={() => setAnalysisExpanded((v) => !v)}
              onClose={() => {
                setAnalysisExpanded(false);
                setSelectedTicker(null);
                setActiveAnalysisTab("technical");
              }}
              onRetry={() => {
                if (selectedTicker) {
                  clearAnalysisForTicker(selectedTicker);
                  runAnalysis(selectedTicker, true, false, ragDocumentDrafts[selectedTicker]);
                }
              }}
              onAnalyze={() => {
                if (selectedTicker) runAnalysis(selectedTicker, false, false, ragDocumentDrafts[selectedTicker]);
              }}
              onFetchTechnicalData={(ticker) => {
                void handleFetchSingleTechnicalData(ticker);
              }}
              ragDocumentText={selectedTicker ? (ragDocumentDrafts[selectedTicker] ?? "") : ""}
              onRagDocumentTextChange={(value: string) => {
                if (!selectedTicker) return;
                setRagDocumentDrafts((prev) => ({ ...prev, [selectedTicker]: value }));
              }}
            />
          </motion.div>
        </div>
      )}
    </div>
  );
}
