"use client";

import Link from "next/link";
import { useState, useEffect, useCallback, useRef } from "react";
import {
  Bot,
  Eye,
  Plus,
  Trash2,
  Play,
  CheckCircle2,
  Calendar,
  AlertCircle,
  Loader2,
  BarChart3,
  Landmark,
  History,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { StockAnalysisPanel } from "@/components/analysis/stock-analysis-panel";
import { cn } from "@/lib/utils";
import { getApiToken, getWatchlist, addToWatchlist, removeFromWatchlist, analyzeStream, chatStream, fetchWatchlistEvents, type WatchlistEvent } from "@/lib/api";
import { mapStructuredToAnalysis } from "@/lib/analysis-utils";
import { useWorkbench } from "@/lib/workbench-context";
import { useUserId } from "@/lib/use-user-id";
import type { WatchlistItem } from "@/lib/types";

type AnalysisStatus = "idle" | "pending" | "running" | "done" | "error";

export default function WatchlistPage() {
  const USER_ID = useUserId();
  const wb = useWorkbench();
  const {
    pendingAnalysisTickers, setPendingAnalysisTickers,
    analysisCache, setAnalysisForTicker,
    analysisLoadingTickers, setTickerAnalysisLoading,
    pushAgentMessage,
    candidates,
  } = wb;

  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addingTicker, setAddingTicker] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [analysisToolStatus, setAnalysisToolStatus] = useState<Record<string, string>>({});
  const [analysisErrors, setAnalysisErrors] = useState<Record<string, string>>({});
  const batchRunningRef = useRef(false);
  const [upcomingEvents, setUpcomingEvents] = useState<WatchlistEvent[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const EVENTS_CACHE_TTL = 24 * 60 * 60 * 1000; // 24h — policy events are static

  // Persistent events cache in sessionStorage (token-scoped)
  const _evtKey = useCallback(() => {
    const token = getApiToken();
    let h = 5381;
    for (let i = 0; i < token.length; i++) h = ((h << 5) + h + token.charCodeAt(i)) >>> 0;
    return `atlas_evt_${h.toString(36)}`;
  }, []);
  const _loadEvtCache = useCallback((): { tickers: string; events: WatchlistEvent[]; ts: number } | null => {
    try { const r = sessionStorage.getItem(_evtKey()); return r ? JSON.parse(r) : null; } catch { return null; }
  }, [_evtKey]);
  const _saveEvtCache = useCallback((data: { tickers: string; events: WatchlistEvent[]; ts: number }) => {
    try { sessionStorage.setItem(_evtKey(), JSON.stringify(data)); } catch { /* quota */ }
  }, [_evtKey]);

  // Right panel state: show stock analysis or event detail
  const [selectedItem, setSelectedItem] = useState<
    { type: "stock"; ticker: string } | { type: "event"; event: WatchlistEvent; key: string } | null
  >(null);
  const [drawerTab, setDrawerTab] = useState<"technical" | "fundamental">("fundamental");
  const [isMobile, setIsMobile] = useState(false);
  const [mobilePanel, setMobilePanel] = useState<"stocks" | "events" | "detail">("stocks");

  useEffect(() => {
    const media = window.matchMedia("(max-width: 767px)");
    const sync = () => setIsMobile(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  // Event card interaction
  const [eventExplanations, setEventExplanations] = useState<Record<string, string>>({});
  const [loadingEventKey, setLoadingEventKey] = useState<string | null>(null);

  const handleEventClick = useCallback(async (ev: WatchlistEvent, key: string) => {
    // Show event in right panel
    setSelectedItem({ type: "event", event: ev, key });
    if (isMobile) setMobilePanel("detail");

    // Upcoming events: show static info, no agent call
    if (ev.days_away > 0) return;

    // Return cached result
    if (eventExplanations[key]) return;

    // Only call agent for events that have already occurred (days_away <= 0)
    setLoadingEventKey(key);
    const isPolicy = ev.category === "policy";
    const prompt = isPolicy
      ? `请简要分析已发生的宏观政策事件：「${ev.event}」（日期：${ev.date}${ev.detail ? `，${ev.detail}` : ''}）。
请说明：1. 这个事件是什么？2. 该事件对大盘和行业板块的实际影响？3. 后续需要关注什么？请用简洁中文回答，控制在150字以内。`
      : `请简要分析 ${ev.ticker} 已发生的事件：「${ev.event}」（日期：${ev.date}${ev.detail ? `，${ev.detail}` : ''}）。
请说明：1. 这个事件是什么？2. 该事件对股价的实际影响？3. 后续需要关注什么？请用简洁中文回答，控制在150字以内。`;

    let text = "";
    try {
      await chatStream(prompt, undefined, {
        onToken: (token) => {
          text += token;
          setEventExplanations((prev) => ({ ...prev, [key]: text }));
        },
      });
    } catch (e) {
      setEventExplanations((prev) => ({ ...prev, [key]: "获取解释失败，请稍后重试。" }));
    } finally {
      setLoadingEventKey(null);
    }
  }, [eventExplanations, isMobile]);

  const loadEvents = useCallback(async (tickers: string[]) => {
    if (tickers.length === 0) {
      setUpcomingEvents([]);
      return;
    }
    const key = tickers.slice().sort().join(",");
    // Restore from persistent cache first (instant display)
    const cached = _loadEvtCache();
    if (cached && cached.tickers === key && Date.now() - cached.ts < EVENTS_CACHE_TTL) {
      setUpcomingEvents(cached.events);
      return;
    }
    // Show stale data immediately while refreshing
    if (cached && cached.tickers === key) {
      setUpcomingEvents(cached.events);
    }
    setEventsLoading(true);
    try {
      const r = await fetchWatchlistEvents(tickers);
      const events = r.events || [];
      setUpcomingEvents(events);
      const entry = { tickers: key, events, ts: Date.now() };
      _saveEvtCache(entry);
    } catch (e) {
      console.error("Failed to load events:", e);
    } finally {
      setEventsLoading(false);
    }
  }, [_loadEvtCache, _saveEvtCache]);

  const loadWatchlist = useCallback(async () => {
    if (!USER_ID) return;  // wait for userId to resolve
    setLoading(true);
    setError(null);
    try {
      const res = await getWatchlist(USER_ID);
      const wl = res.watchlist || [];
      setItems(wl);
      loadEvents(wl.map((i) => i.ticker));
    } catch (err) {
      console.error("Failed to load watchlist:", err);
      setError("加载失败，显示示例数据");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [USER_ID, loadEvents]);

  useEffect(() => {
    loadWatchlist();
  }, [loadWatchlist]);

  const handleAdd = async () => {
    const ticker = addingTicker.trim().toUpperCase();
    if (!ticker) return;
    setAddError(null);
    try {
      await addToWatchlist(USER_ID, ticker);
      setAddingTicker("");
      loadWatchlist();
    } catch (err) {
      setAddError(`添加失败: ${err instanceof Error ? err.message : "无法匹配该代码"}`);
      setTimeout(() => setAddError(null), 3000);
    }
  };

  const handleRemove = async (ticker: string) => {
    if (!confirm(`确认移除 ${ticker}？`)) return;
    try {
      await removeFromWatchlist(USER_ID, ticker);
      setPendingAnalysisTickers((prev) => prev.filter((t) => t !== ticker));
      loadWatchlist();
    } catch (err) {
      alert(`移除失败: ${err instanceof Error ? err.message : "未知错误"}`);
    }
  };

  // Get analysis status for a ticker
  const getStatus = useCallback((ticker: string): AnalysisStatus => {
    if (analysisCache[ticker]) return "done";
    if (analysisLoadingTickers.has(ticker)) return "running";
    if (analysisErrors[ticker]) return "error";
    if (pendingAnalysisTickers.includes(ticker)) return "pending";
    return "idle";
  }, [analysisCache, analysisLoadingTickers, analysisErrors, pendingAnalysisTickers]);

  // Run analysis for a single ticker
  const runSingleAnalysis = useCallback(async (ticker: string) => {
    if (analysisLoadingTickers.has(ticker) || analysisCache[ticker]) return;
    setTickerAnalysisLoading(ticker, true);
    setAnalysisErrors((prev) => { const n = { ...prev }; delete n[ticker]; return n; });
    setAnalysisToolStatus((prev) => ({ ...prev, [ticker]: "正在启动分析..." }));

    try {
      const res = await analyzeStream(ticker, undefined, {
        onStepStart: (node) => {
          const labels: Record<string, string> = {
            gather_data: "正在获取财务数据",
            sentiment: "正在分析市场情绪",
            synthesis: "正在生成分析报告",
            render_output: "正在渲染报告",
          };
          setAnalysisToolStatus((prev) => ({ ...prev, [ticker]: (labels[node] || node) + "..." }));
        },
        onToolStart: (tool) => {
          const labels: Record<string, string> = {
            get_company_profile: "获取公司概况",
            get_key_metrics: "获取核心指标",
            get_financial_statements: "获取财务报表",
            get_peer_comparison: "同业对比分析",
            get_risk_metrics: "获取风险指标",
            get_catalysts: "获取催化剂信息",
            get_company_news: "获取公司新闻",
            get_policy_events: "获取政策事件",
            web_search: "搜索补充信息",
          };
          setAnalysisToolStatus((prev) => ({ ...prev, [ticker]: `${labels[tool] || tool}...` }));
        },
        onStepEnd: () => {},
        onToolEnd: () => {},
      });

      const analysis = mapStructuredToAnalysis(
        res.ticker,
        res.structured,
        res.report,
        res.errors,
        res.evidence_chain,
        res.retrieval_debug,
      );
      setAnalysisForTicker(res.ticker, analysis);
      // Remove from pending
      setPendingAnalysisTickers((prev) => prev.filter((t) => t !== ticker));
      pushAgentMessage(`✅ **${ticker}** 深度分析完成，可在观察组查看。`, true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "分析失败";
      setAnalysisErrors((prev) => ({ ...prev, [ticker]: msg }));
      pushAgentMessage(`⚠️ **${ticker}** 分析失败：${msg}`, true);
    } finally {
      setTickerAnalysisLoading(ticker, false);
      setAnalysisToolStatus((prev) => { const n = { ...prev }; delete n[ticker]; return n; });
    }
  }, [analysisCache, analysisLoadingTickers, setAnalysisForTicker, setTickerAnalysisLoading, setPendingAnalysisTickers, pushAgentMessage]);

  // Batch analysis: run pending tickers concurrently
  const runBatchAnalysis = useCallback(async () => {
    if (batchRunningRef.current) return;
    batchRunningRef.current = true;
    const tickers = items
      .map((i) => i.ticker)
      .filter((t) => pendingAnalysisTickers.includes(t) && !analysisCache[t] && !analysisLoadingTickers.has(t));

    await Promise.allSettled(tickers.map((ticker) => runSingleAnalysis(ticker)));
    batchRunningRef.current = false;
  }, [items, pendingAnalysisTickers, analysisCache, analysisLoadingTickers, runSingleAnalysis]);

  // Click row to view in right panel
  const handleRowClick = (ticker: string) => {
    setSelectedItem({ type: "stock", ticker });
    setDrawerTab("fundamental");
    if (isMobile) setMobilePanel("detail");
  };

  // Derived: currently selected ticker for right panel
  const activeTicker = selectedItem?.type === "stock" ? selectedItem.ticker : null;

  const hasPending = items.some((i) => pendingAnalysisTickers.includes(i.ticker) && !analysisCache[i.ticker]);
  const hasAnyRunning = items.some((i) => analysisLoadingTickers.has(i.ticker));
  const doneCount = items.filter((i) => analysisCache[i.ticker]).length;

  const stockListPanel = (
    <>
      <div className="shrink-0 px-4 py-4 border-b border-theme">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h1 className="text-base font-semibold text-theme-primary">观察组</h1>
            <p className="text-[11px] text-zinc-500 mt-0.5">
              {items.length} 只标的
              {doneCount > 0 && <span className="text-emerald-400 ml-1">· {doneCount} 已分析</span>}
            </p>
          </div>
          {hasPending && (
            <button
              onClick={runBatchAnalysis}
              disabled={hasAnyRunning}
              className={cn(
                "inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium transition-colors",
                hasAnyRunning
                  ? "bg-zinc-800 text-zinc-500 cursor-not-allowed"
                  : "bg-brand/15 text-brand hover:bg-brand/25"
              )}
            >
              {hasAnyRunning ? (
                <><Loader2 className="w-3 h-3 animate-spin" /> 分析中</>
              ) : (
                <><Play className="w-3 h-3" /> 批量</>
              )}
            </button>
          )}
        </div>
        <div className="mb-3 rounded-xl border border-zinc-800/50 bg-surface-1 p-3">
          <div className="flex items-start gap-2.5">
            <Bot className="w-4 h-4 text-brand shrink-0 mt-0.5" />
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium text-zinc-200">需要常驻投研助手？</p>
              <p className="mt-1 text-[11px] leading-5 text-zinc-500">
                观察组负责维护标的，常驻 Agent 的开启、巡检频率和历史记录统一在 Agent 页管理。
              </p>
            </div>
          </div>
          <div className="mt-2 flex items-center justify-between">
            <span className="text-[10px] text-zinc-500">前往 Agent 页开启或查看常驻模式</span>
            <Link href="/agent" className="text-[10px] text-brand hover:underline">进入 Agent 页</Link>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <input
            value={addingTicker}
            onChange={(e) => { setAddingTicker(e.target.value); setAddError(null); }}
            onKeyDown={(e) => e.key === "Enter" && handleAdd()}
            placeholder="如 AAPL、TSLA"
            className={cn(
              "flex-1 px-2.5 py-1.5 rounded-lg bg-surface-1 border text-xs text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors",
              addError ? "border-rose-500/50 focus:border-rose-500/70" : "border-zinc-800/50 focus:border-brand/40"
            )}
          />
          <button
            onClick={handleAdd}
            className="inline-flex items-center gap-1 px-2 py-1.5 rounded-lg bg-brand/15 text-brand text-[11px] font-medium hover:bg-brand/25 transition-colors"
          >
            <Plus className="w-3 h-3" />
          </button>
        </div>
        {addError && (
          <div className="flex items-center gap-1.5 mt-1 text-[11px] text-rose-400">
            <AlertCircle className="w-3 h-3 shrink-0" />
            {addError}
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="w-5 h-5 text-brand animate-spin" />
          </div>
        ) : items.length === 0 ? (
          <p className="text-xs text-zinc-500 text-center py-8">暂无标的，请添加</p>
        ) : (
          <div className="px-2 py-2 space-y-0.5">
            {items.map((item) => {
              const status = getStatus(item.ticker);
              const toolSt = analysisToolStatus[item.ticker];
              const isActive = activeTicker === item.ticker;
              return (
                <div
                  key={item.ticker}
                  onClick={() => handleRowClick(item.ticker)}
                  className={cn(
                    "flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors cursor-pointer",
                    isActive
                      ? "bg-brand/8 border border-brand/20"
                      : "hover:bg-surface-2/50 border border-transparent"
                  )}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-zinc-100">{item.ticker}</span>
                      {status === "done" && <CheckCircle2 className="w-3 h-3 text-emerald-400" />}
                      {status === "running" && <Loader2 className="w-3 h-3 text-brand animate-spin" />}
                      {status === "error" && <AlertCircle className="w-3 h-3 text-rose-400" />}
                    </div>
                    {status === "running" && toolSt && (
                      <p className="text-[10px] text-brand mt-0.5 truncate">{toolSt}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                    {(status === "idle" || status === "pending" || status === "error") && (
                      <button
                        onClick={() => {
                          if (!pendingAnalysisTickers.includes(item.ticker)) {
                            setPendingAnalysisTickers((prev) => [...prev, item.ticker]);
                          }
                          runSingleAnalysis(item.ticker);
                        }}
                        className="p-1 rounded-md text-zinc-500 hover:text-brand hover:bg-brand/10 transition-colors"
                        title={status === "error" ? "重试分析" : "开始分析"}
                      >
                        <Play className="w-3 h-3" />
                      </button>
                    )}
                    <button
                      onClick={() => handleRemove(item.ticker)}
                      className="p-1 rounded-md text-zinc-500 hover:text-rose-400 hover:bg-rose-400/10 transition-colors"
                      title="移除"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );

  const eventsPanel = (
    <>
      <div className="shrink-0 px-4 py-4 border-b border-theme flex items-center gap-1.5">
        <Calendar className="w-3.5 h-3.5 text-amber-400" />
        <span className="text-sm font-medium text-theme-primary">事件日历</span>
        <span className="text-[10px] text-zinc-500 ml-auto">{upcomingEvents.length} 条</span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {eventsLoading ? (
          <div className="flex items-center gap-2 justify-center h-32">
            <Loader2 className="w-4 h-4 text-zinc-500 animate-spin" />
            <span className="text-[11px] text-zinc-500">加载中...</span>
          </div>
        ) : upcomingEvents.length === 0 ? (
          <p className="text-[11px] text-zinc-500 text-center py-8">暂无事件</p>
        ) : (() => {
          const pastEvents = upcomingEvents.filter((e) => e.days_away <= 0);
          const futureEvents = upcomingEvents.filter((e) => e.days_away > 0);
          const pastTicker = pastEvents.filter((e) => e.category !== "policy");
          const pastPolicy = pastEvents.filter((e) => e.category === "policy");
          const futureTicker = futureEvents.filter((e) => e.category !== "policy");
          const futurePolicy = futureEvents.filter((e) => e.category === "policy");
          return (
            <div className="px-2 py-2 space-y-0">
              {/* ── 已发生事件 ── */}
              {pastEvents.length > 0 && (
                <>
                  <div className="flex items-center gap-1.5 px-2 pt-1 pb-1.5">
                    <History className="w-3 h-3 text-emerald-400" />
                    <span className="text-[10px] font-medium text-emerald-400 uppercase tracking-wide">已发生</span>
                    <span className="text-[10px] text-zinc-600">{pastEvents.length}</span>
                  </div>
                  {pastTicker.slice(0, 10).map((ev, i) => {
                    const key = `past-${ev.ticker}-${ev.event}-${i}`;
                    const isActive = selectedItem?.type === "event" && selectedItem.key === key;
                    return (
                      <button
                        key={key}
                        onClick={() => handleEventClick(ev, key)}
                        className={cn(
                          "w-full flex items-center justify-between px-3 py-2 rounded-lg text-left transition-colors mb-0.5",
                          isActive
                            ? "bg-emerald-400/8 border border-emerald-400/20"
                            : "hover:bg-surface-2/50 border border-transparent"
                        )}
                      >
                        <div className="flex-1 min-w-0 flex items-center gap-1.5">
                          <span className="text-[11px] font-medium text-zinc-200">{ev.ticker}</span>
                          <span className="text-[11px] text-zinc-500 truncate">{ev.event}</span>
                        </div>
                        <span className="text-[10px] px-1.5 py-0.5 rounded shrink-0 ml-2 text-emerald-400 bg-emerald-400/10">
                          {Math.abs(ev.days_away)}天前
                        </span>
                      </button>
                    );
                  })}
                  {pastPolicy.slice(0, 8).map((ev, i) => {
                    const key = `past-policy-${ev.event}-${i}`;
                    const isActive = selectedItem?.type === "event" && selectedItem.key === key;
                    return (
                      <button
                        key={key}
                        onClick={() => handleEventClick(ev, key)}
                        className={cn(
                          "w-full flex items-center justify-between px-3 py-2 rounded-lg text-left transition-colors mb-0.5",
                          isActive
                            ? "bg-blue-400/8 border border-blue-400/20"
                            : "hover:bg-surface-2/50 border border-transparent"
                        )}
                      >
                        <div className="flex-1 min-w-0 flex items-center gap-1.5">
                          <Landmark className="w-3 h-3 text-blue-400 shrink-0" />
                          <span className="text-[11px] font-medium text-blue-300 truncate">{ev.event}</span>
                        </div>
                        <span className="text-[10px] px-1.5 py-0.5 rounded shrink-0 ml-2 text-emerald-400 bg-emerald-400/10">
                          {Math.abs(ev.days_away)}天前
                        </span>
                      </button>
                    );
                  })}
                  <div className="border-t border-zinc-800/40 my-1.5" />
                </>
              )}
              {/* ── 即将到来 ── */}
              {futureEvents.length > 0 && (
                <>
                  <div className="flex items-center gap-1.5 px-2 pt-1 pb-1.5">
                    <Calendar className="w-3 h-3 text-amber-400" />
                    <span className="text-[10px] font-medium text-zinc-400 uppercase tracking-wide">即将到来</span>
                    <span className="text-[10px] text-zinc-600">{futureEvents.length}</span>
                  </div>
                  {futureTicker.slice(0, 15).map((ev, i) => {
                    const key = `${ev.ticker}-${ev.event}-${i}`;
                    const isActive = selectedItem?.type === "event" && selectedItem.key === key;
                    return (
                      <button
                        key={key}
                        onClick={() => handleEventClick(ev, key)}
                        className={cn(
                          "w-full flex items-center justify-between px-3 py-2 rounded-lg text-left transition-colors mb-0.5",
                          isActive
                            ? "bg-amber-400/8 border border-amber-400/20"
                            : "hover:bg-surface-2/50 border border-transparent"
                        )}
                      >
                        <div className="flex-1 min-w-0 flex items-center gap-1.5">
                          <span className="text-[11px] font-medium text-zinc-200">{ev.ticker}</span>
                          <span className="text-[11px] text-zinc-500 truncate">{ev.event}</span>
                        </div>
                        <span className={cn(
                          "text-[10px] px-1.5 py-0.5 rounded shrink-0 ml-2",
                          ev.days_away <= 3 ? "text-amber-400 bg-amber-400/10" :
                          ev.days_away <= 14 ? "text-zinc-300 bg-surface-2" :
                          "text-zinc-500 bg-surface-2"
                        )}>
                          {ev.days_away === 0 ? "今天" : `${ev.days_away}天`}
                        </span>
                      </button>
                    );
                  })}
                  {futurePolicy.slice(0, 10).map((ev, i) => {
                    const key = `policy-${ev.event}-${i}`;
                    const isActive = selectedItem?.type === "event" && selectedItem.key === key;
                    return (
                      <button
                        key={key}
                        onClick={() => handleEventClick(ev, key)}
                        className={cn(
                          "w-full flex items-center justify-between px-3 py-2 rounded-lg text-left transition-colors mb-0.5",
                          isActive
                            ? "bg-blue-400/8 border border-blue-400/20"
                            : "hover:bg-surface-2/50 border border-transparent"
                        )}
                      >
                        <div className="flex-1 min-w-0 flex items-center gap-1.5">
                          <Landmark className="w-3 h-3 text-blue-400 shrink-0" />
                          <span className="text-[11px] font-medium text-blue-300 truncate">{ev.event}</span>
                        </div>
                        <span className={cn(
                          "text-[10px] px-1.5 py-0.5 rounded shrink-0 ml-2",
                          ev.days_away <= 3 ? "text-amber-400 bg-amber-400/10" :
                          ev.days_away <= 14 ? "text-zinc-300 bg-surface-2" :
                          "text-zinc-500 bg-surface-2"
                        )}>
                          {ev.days_away}天
                        </span>
                      </button>
                    );
                  })}
                </>
              )}
            </div>
          );
        })()}
      </div>
    </>
  );

  const detailPanel = (
    <>
      {selectedItem?.type === "stock" && activeTicker ? (
        <StockAnalysisPanel
          analysis={analysisCache[activeTicker] ?? null}
          loading={analysisLoadingTickers.has(activeTicker)}
          toolStatus={analysisToolStatus[activeTicker] || null}
          ticker={activeTicker}
          selectedStock={candidates.find((s) => s.ticker === activeTicker) ?? null}
          activeTab={drawerTab}
          onTabChange={setDrawerTab}
          onClose={() => {
            setSelectedItem(null);
            if (isMobile) setMobilePanel("stocks");
          }}
          onRetry={() => {
            setAnalysisForTicker(activeTicker, undefined as any);
            runSingleAnalysis(activeTicker);
          }}
          onAnalyze={() => {
            if (!pendingAnalysisTickers.includes(activeTicker)) {
              setPendingAnalysisTickers((prev) => [...prev, activeTicker]);
            }
            runSingleAnalysis(activeTicker);
          }}
        />
      ) : selectedItem?.type === "event" ? (
        <div className="flex flex-col h-full">
          <div className="shrink-0 px-5 py-4 border-b border-theme flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                {selectedItem.event.category === "policy"
                  ? <Landmark className="w-4 h-4 text-blue-400" />
                  : <Calendar className="w-4 h-4 text-amber-400" />}
                <h2 className="text-sm font-semibold text-theme-primary">{selectedItem.event.category === "policy" ? selectedItem.event.event : selectedItem.event.ticker}</h2>
                {selectedItem.event.category === "policy"
                  ? <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-400">政策</span>
                  : <span className="text-xs text-theme-muted">{selectedItem.event.event}</span>}
              </div>
              <p className="text-[11px] text-zinc-500 mt-0.5">
                {selectedItem.event.date} · 距今 {selectedItem.event.days_away} 天
                {selectedItem.event.detail && ` · ${selectedItem.event.detail}`}
              </p>
            </div>
            <button
              onClick={() => {
                setSelectedItem(null);
                if (isMobile) setMobilePanel("events");
              }}
              className="text-zinc-500 hover:text-zinc-300 transition-colors p-1 rounded hover:bg-surface-2"
            >
              <Eye className="w-4 h-4" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto px-5 py-4">
            {loadingEventKey === selectedItem.key && !eventExplanations[selectedItem.key] ? (
              <div className="flex items-center gap-3 rounded-xl bg-brand/5 border border-brand/10 p-4">
                <Loader2 className="w-5 h-5 text-brand animate-spin" />
                <div>
                  <p className="text-sm font-medium text-theme-primary">Agent 分析中...</p>
                  <p className="text-xs text-theme-muted mt-0.5">正在分析该事件的影响</p>
                </div>
              </div>
            ) : eventExplanations[selectedItem.key] ? (
              <div className="rounded-xl bg-surface-1 border border-zinc-800/50 p-5">
                <h3 className="text-sm font-medium text-zinc-200 mb-3 flex items-center gap-1.5">
                  <BarChart3 className="w-3.5 h-3.5 text-brand" />
                  事件分析
                </h3>
                <div className="text-sm text-zinc-300 leading-relaxed prose prose-invert prose-sm max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {eventExplanations[selectedItem.key]}
                  </ReactMarkdown>
                </div>
              </div>
            ) : selectedItem.event.days_away > 0 ? (
              <div className="space-y-4">
                <div className="rounded-xl bg-surface-1 border border-zinc-800/50 p-5">
                  <h3 className="text-sm font-medium text-zinc-200 mb-3">事件预告</h3>
                  <div className="space-y-2 text-sm text-zinc-300">
                    <p><span className="text-zinc-500">事件：</span>{selectedItem.event.event}</p>
                    <p><span className="text-zinc-500">日期：</span>{selectedItem.event.date}</p>
                    <p><span className="text-zinc-500">倒计时：</span>{selectedItem.event.days_away} 天</p>
                    {selectedItem.event.detail && <p><span className="text-zinc-500">备注：</span>{selectedItem.event.detail}</p>}
                    {selectedItem.event.ticker && selectedItem.event.category !== "policy" && (
                      <p><span className="text-zinc-500">标的：</span>{selectedItem.event.ticker}</p>
                    )}
                  </div>
                </div>
                <div className="rounded-xl bg-amber-400/5 border border-amber-400/15 p-4">
                  <p className="text-xs text-amber-300/80">⏳ 该事件尚未发生，事件发生后将自动拉取最新信息并进行 Agent 分析。</p>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <Calendar className="w-10 h-10 text-zinc-600 mb-3" />
                <p className="text-sm text-zinc-400">点击后自动分析事件影响</p>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center h-full text-center px-6">
          <div className="w-16 h-16 rounded-2xl bg-surface-1 border border-zinc-800/50 flex items-center justify-center mb-4">
            <Eye className="w-7 h-7 text-zinc-600" />
          </div>
          <p className="text-sm text-zinc-400">选择标的或事件查看详情</p>
          <p className="text-xs text-zinc-600 mt-1">点击左侧列表项查看分析</p>
        </div>
      )}
    </>
  );

  return (
    <div className="h-full flex flex-col md:flex-row overflow-hidden">
      {isMobile ? (
        <>
          <div className="shrink-0 border-b border-theme px-3 py-2 flex items-center gap-2 overflow-x-auto">
            <button
              onClick={() => setMobilePanel("stocks")}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors",
                mobilePanel === "stocks" ? "bg-brand/10 text-brand" : "text-zinc-500 hover:text-zinc-300 hover:bg-surface-2"
              )}
            >
              标的
            </button>
            <button
              onClick={() => setMobilePanel("events")}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors",
                mobilePanel === "events" ? "bg-brand/10 text-brand" : "text-zinc-500 hover:text-zinc-300 hover:bg-surface-2"
              )}
            >
              事件
            </button>
            <button
              onClick={() => setMobilePanel("detail")}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors",
                mobilePanel === "detail" ? "bg-brand/10 text-brand" : "text-zinc-500 hover:text-zinc-300 hover:bg-surface-2"
              )}
            >
              详情
            </button>
          </div>
          <div className="flex-1 min-h-0 overflow-hidden">
            {mobilePanel === "stocks" ? (
              <div className="h-full flex flex-col overflow-hidden">{stockListPanel}</div>
            ) : mobilePanel === "events" ? (
              <div className="h-full flex flex-col overflow-hidden">{eventsPanel}</div>
            ) : (
              <div className="h-full flex flex-col overflow-hidden">{detailPanel}</div>
            )}
          </div>
        </>
      ) : (
        <>
          <div className="w-[280px] shrink-0 flex flex-col border-r border-theme">{stockListPanel}</div>
          <div className="w-[280px] shrink-0 flex flex-col border-r border-theme">{eventsPanel}</div>
          <div className="flex-1 flex flex-col overflow-hidden">{detailPanel}</div>
        </>
      )}
    </div>
  );
}
