"use client";

import { useRef, useEffect, useCallback, useState } from "react";
import { Activity, Maximize2, Minimize2, MessageSquarePlus, History, X } from "lucide-react";
import type { ChatMessage } from "@/lib/types";
import { chatStream, resumeChat, fetchStrongStocks } from "@/lib/api";
import { useWorkbench, type ChatSession } from "@/lib/workbench-context";
import { MessageBubble } from "./message-bubble";
import { PromptInput } from "./prompt-input";
import { QuickPrompts } from "./quick-prompts";
import { FollowupPrompts } from "./followup-prompts";
import { ConfigChipBar } from "./config-chip-bar";
import { ConfigDrawer } from "./config-drawer";

const NODE_LABELS: Record<string, string> = {
  strong_stocks: "正在获取强势股数据",
  gather_data: "正在获取财务数据",
  sentiment: "正在分析市场情绪",
  synthesis: "正在生成分析报告",
  render_output: "正在渲染报告",
  update_config: "正在更新监控参数",
  watchlist_add: "正在添加到观察组",
};

const TOOL_LABELS: Record<string, string> = {
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

const SORT_LABELS: Record<string, string> = {
  momentum_score: "综合动量评分",
  performance_20d: "20日涨幅",
  performance_40d: "40日涨幅",
  performance_90d: "90日涨幅",
  performance_180d: "180日涨幅",
  rs_20d: "相对强度(超额)",
  vol_score: "量价配合",
  trend_r2: "趋势平滑度",
  volume_5d_avg: "5日成交额",
};

interface ChatPanelProps {
  onConfigApply?: (stocks: Record<string, unknown>[]) => void;
  onChatResponse?: (message: string) => void;
  onAnalyzeStock?: (ticker: string) => void;
  expanded?: boolean;
  onToggleExpand?: () => void;
}

export function ChatPanel({ onConfigApply, onChatResponse, onAnalyzeStock, expanded, onToggleExpand }: ChatPanelProps) {
  const wb = useWorkbench();
  const {
    messages, setMessages,
    sessionId, setSessionId,
    showWelcome, setShowWelcome,
    config, setConfig,
    watchedTickers, setWatchedTickers,
    chatHistory, saveAndNewSession, switchToSession, deleteSession,
  } = wb;

  const [activeStreams, setActiveStreams] = useState(0);
  const isLoading = activeStreams > 0;
  const [error, setError] = useState<string | null>(null);
  const [toolStatus, setToolStatus] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const applyLockRef = useRef(false);
  const tickerSelectedRef = useRef<string | null>(null);
  const multiAnalyzeRef = useRef<string[] | null>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, toolStatus]);

  const handleSend = useCallback(async (message: string) => {
    setShowWelcome(false);
    setError(null);
    const userMsg: ChatMessage = { role: "user", content: message };
    // Append user msg + empty assistant placeholder; capture the placeholder index
    let msgIndex = -1;
    setMessages((prev) => {
      msgIndex = prev.length + 1; // index of assistant placeholder
      return [...prev, userMsg, { role: "assistant", content: "" }];
    });
    setActiveStreams((n) => n + 1);
    let streamContent = "";
    const localTickerSelected = { current: null as string | null };
    const localMultiAnalyze = { current: null as string[] | null };

    try {
      const sid = await chatStream(message, sessionId, {
        onToken: (token) => {
          // Suppress chat tokens when analysis was redirected to right panel
          if (localTickerSelected.current) return;
          streamContent += token;
          const text = streamContent;
          setMessages((prev) => {
            const copy = [...prev];
            if (msgIndex >= 0 && msgIndex < copy.length) {
              copy[msgIndex] = { role: "assistant", content: text };
            }
            return copy;
          });
        },
        onStepStart: (node) => {
          const label = NODE_LABELS[node] || node;
          setToolStatus(`${label}...`);
        },
        onStepEnd: () => {
          setToolStatus(null);
        },
        onToolStart: (tool) => {
          const label = TOOL_LABELS[tool] || tool;
          setToolStatus(`${label}...`);
        },
        onToolEnd: () => {
          setToolStatus(null);
        },
        onConfigUpdate: (params) => {
          let merged: typeof config;
          setConfig((prev) => {
            merged = { ...prev, ...params } as typeof prev;
            return merged;
          });
          // Auto-fetch strong stocks with updated config
          fetchStrongStocks({
            market_type: merged!.market_type,
            top_count: merged!.top_count,
            rsi_threshold: merged!.rsi_threshold,
            sort_by: merged!.sort_by,
            min_volume_turnover: merged!.min_volume_turnover,
          }).then((res) => {
            onConfigApply?.(res.stocks || []);
          }).catch((err) => {
            console.error("Auto-fetch after config update failed:", err);
          });
        },
        onWatchlistUpdate: (tickers, action) => {
          setWatchedTickers((prev) => {
            const next = new Set(prev);
            if (action === "remove") {
              tickers.forEach((t) => next.delete(t));
            } else {
              tickers.forEach((t) => next.add(t));
            }
            return next;
          });
        },
        onTickerSelect: (ticker, name) => {
          if (localTickerSelected.current === ticker) return;
          localTickerSelected.current = ticker;
          tickerSelectedRef.current = ticker;
          const label = name ? `${name} (${ticker})` : ticker;
          setMessages((prev) => {
            const copy = [...prev];
            if (msgIndex >= 0 && msgIndex < copy.length) {
              copy[msgIndex] = {
                role: "assistant",
                content: `📊 **${label}** 深度分析已启动，请查看右侧面板...`,
              };
            }
            return copy;
          });
          onAnalyzeStock?.(ticker);
        },
        onResolveFail: (_query, message) => {
          setMessages((prev) => {
            const copy = [...prev];
            if (msgIndex >= 0 && msgIndex < copy.length) {
              copy[msgIndex] = {
                role: "assistant",
                content: `⚠️ ${message}`,
              };
            }
            return copy;
          });
        },
        onMultiAnalyze: (tickers) => {
          localMultiAnalyze.current = tickers;
          wb.setPendingAnalysisTickers((prev) => {
            const s = new Set(prev);
            tickers.forEach((t) => s.add(t));
            return Array.from(s);
          });
        },
        onHarnessEvent: (ev) => {
          const labels: Record<string, string> = {
            recovery: (() => {
              const lvl = ev.level_name || ev.level;
              const node = ev.node || "";
              if (lvl === "retry" || lvl === 1)
                return `Harness: ${node} 数据获取失败，正在重试 (${ev.attempt || ""}/${ev.max_retry || ""})...`;
              if (lvl === "fallback" || lvl === 2)
                return `Harness: ${node} 主数据源不可用，切换备用源 (${ev.resolution || ""})`;
              if (lvl === "degrade" || lvl === 3)
                return `Harness: ${node} 所有数据源失败，已降级处理，分析可能不完整`;
              if (lvl === "escalate" || lvl === 4)
                return `Harness: ${node} 恢复失败，已上报 — 请检查网络连接后重试`;
              return `Harness: ${node} 触发恢复链 (${lvl})`;
            })(),
            compaction: `Harness: 上下文压缩 — 对话历史 ${ev.before_messages || "?"} → ${ev.after_messages || "?"} 条 (使用率 ${((ev.usage_ratio as number) * 100 || 0).toFixed(0)}%)`,
            circuit_breaker: `Harness: 熔断器 ${ev.breaker || ""} 状态变更 → ${ev.state || ""}`,
          };
          const text = labels[ev.module] || `Harness: ${ev.module} 事件`;
          setMessages((prev) => [...prev, { role: "system" as const, content: text, isSystem: true }]);
        },
        onIntentDone: (intent, content, index, total) => {
          // Finalize current assistant bubble with the completed intent's content
          // and create a new placeholder for the next intent.
          setMessages((prev) => {
            const copy = [...prev];
            if (msgIndex >= 0 && msgIndex < copy.length) {
              copy[msgIndex] = { role: "assistant", content };
            }
            // Push new placeholder for next intent (if more remain)
            if (index < total - 1) {
              copy.push({ role: "assistant", content: "" });
              msgIndex = copy.length - 1;
            }
            return copy;
          });
          streamContent = ""; // reset for next intent
        },
        onDisambiguate: (tickers, sid) => {
          // Show disambiguation options as clickable buttons
          setMessages((prev) => {
            const copy = [...prev];
            if (msgIndex >= 0 && msgIndex < copy.length) {
              copy[msgIndex] = {
                role: "assistant",
                content: `❓ 找到多个可能的标的，请选择你要分析的：`,
                disambiguateOptions: tickers,
              };
            }
            return copy;
          });
          if (sid) setSessionId(sid);
        },
        onDone: (newSid) => {
          setSessionId(newSid);
          if (localMultiAnalyze.current?.length) {
            const tStr = localMultiAnalyze.current.join("、");
            setMessages((prev) => {
              const copy = [...prev];
              if (msgIndex >= 0 && msgIndex < copy.length) {
                copy[msgIndex] = {
                  role: "assistant",
                  content: `📋 已将 **${tStr}** 加入观察组。\n\n请前往侧边栏 **「观察组」** 页面，启动深度分析并查看进度。`,
                };
              }
              return copy;
            });
            localMultiAnalyze.current = null;
          }
          onChatResponse?.(streamContent);
        },
      });
      if (sid) setSessionId(sid);
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : "请求失败";
      setError(errMsg);
      setMessages((prev) => {
        const copy = [...prev];
        if (msgIndex >= 0 && msgIndex < copy.length) {
          copy[msgIndex] = { role: "assistant", content: `⚠️ ${errMsg}` };
        }
        return copy;
      });
    } finally {
      setActiveStreams((n) => Math.max(0, n - 1));
      setToolStatus(null);
    }
  }, [sessionId, setMessages, setSessionId, setShowWelcome, config, setConfig, watchedTickers, setWatchedTickers, onConfigApply, onChatResponse, onAnalyzeStock]);

  // --- Disambiguation: user picks a ticker from ambiguous options ---
  const handleDisambiguate = useCallback(async (ticker: string) => {
    if (!sessionId) return;
    setActiveStreams((n) => n + 1);
    setToolStatus("正在继续分析...");
    // Replace disambiguation message with selection confirmation
    const disambigIdx = messages.length - 1;
    setMessages((prev) => {
      const copy = [...prev];
      copy[disambigIdx] = { role: "assistant", content: `✅ 已选择 **${ticker}**，正在继续分析...` };
      return copy;
    });
    let resumeContent = "";
    const localTickerSel = { current: null as string | null };
    try {
      await resumeChat(sessionId, ticker, {
        onToken: (token) => {
          if (localTickerSel.current) return;
          resumeContent += token;
          const text = resumeContent;
          setMessages((prev) => {
            const copy = [...prev];
            copy[disambigIdx] = { role: "assistant", content: text };
            return copy;
          });
        },
        onStepStart: (node, tools) => {
          const label = NODE_LABELS[node] || node;
          const toolNames = tools.length ? ` (${tools.join(", ")})` : "";
          setToolStatus(`${label}${toolNames}...`);
        },
        onStepEnd: () => setToolStatus(null),
        onToolStart: (tool) => setToolStatus(`${TOOL_LABELS[tool] || tool}...`),
        onToolEnd: () => setToolStatus(null),
        onTickerSelect: (t) => {
          localTickerSel.current = t;
          tickerSelectedRef.current = t;
          setMessages((prev) => {
            const copy = [...prev];
            copy[disambigIdx] = {
              role: "assistant",
              content: `📊 **${t}** 深度分析已启动，请查看右侧面板...`,
            };
            return copy;
          });
          onAnalyzeStock?.(t);
        },
        onDone: () => {
          onChatResponse?.(resumeContent);
        },
      });
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "恢复失败";
      setMessages((prev) => {
        const copy = [...prev];
        copy[disambigIdx] = { role: "assistant", content: `⚠️ ${errMsg}` };
        return copy;
      });
    } finally {
      setActiveStreams((n) => Math.max(0, n - 1));
      setToolStatus(null);
    }
  }, [sessionId, messages.length, setMessages, onAnalyzeStock, onChatResponse]);

  // --- New conversation ---
  const handleNewConversation = useCallback(() => {
    if (isLoading) return;
    saveAndNewSession();
    setError(null);
    setToolStatus(null);
    tickerSelectedRef.current = null;
    multiAnalyzeRef.current = null;
    setHistoryOpen(false);
  }, [isLoading, saveAndNewSession]);

  // --- History panel toggle ---
  const [historyOpen, setHistoryOpen] = useState(false);

  const handleSwitchSession = useCallback((id: string) => {
    if (isLoading) return;
    switchToSession(id);
    setHistoryOpen(false);
    setError(null);
    setToolStatus(null);
    tickerSelectedRef.current = null;
    multiAnalyzeRef.current = null;
  }, [isLoading, switchToSession]);

  const handleQuickPrompt = (prompt: string) => {
    handleSend(prompt);
  };

  const handleApplyConfig = useCallback(async () => {
    // Debounce: prevent rapid repeated clicks
    if (applyLockRef.current || isLoading) return;
    applyLockRef.current = true;
    setTimeout(() => { applyLockRef.current = false; }, 2000);

    setShowWelcome(false);
    setActiveStreams((n) => n + 1);
    setToolStatus("正在获取强势股数据 (get_strong_stocks)...");

    const mktLabel = config.market_type === "us_stock" ? "美股" : config.market_type === "hk_stock" ? "港股" : "ETF";
    setMessages((prev) => [
      ...prev,
      { role: "user", content: `筛选强势股: ${mktLabel} | 每周期 ${config.top_count} 只 | RSI>${config.rsi_threshold} | 排序 ${SORT_LABELS[config.sort_by] || config.sort_by}` },
    ]);
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    try {
      const res = await fetchStrongStocks({
        market_type: config.market_type,
        top_count: config.top_count,
        rsi_threshold: config.rsi_threshold,
        sort_by: config.sort_by,
        min_volume_turnover: config.min_volume_turnover,
      });
      const stocks = res.stocks || [];
      let text = `## ${mktLabel} 强势股 (${stocks.length} 只) — 排序: ${SORT_LABELS[config.sort_by] || config.sort_by}\n\n`;
      if (stocks.length === 0) {
        text += "暂无符合条件的强势股数据。";
      } else {
        text += "| # | 代码 | 名称 | 价格 | 20日 | 90日 | 超额 | 量价比 | 趋势R² | 综合分 |\n";
        text += "|---|------|------|------|------|------|------|--------|--------|--------|\n";
        stocks.forEach((s: Record<string, unknown>, i: number) => {
          const fmt = (v: unknown, suf = "%") => v != null ? Number(v).toFixed(1) + suf : "-";
          const fmtS = (v: unknown) => v != null ? Number(v).toFixed(2) : "-";
          text += `| ${i + 1} | ${s.symbol || ""} | ${s.name || ""} | ${fmtS(s.current_price)} | ${fmt(s.performance_20d)} | ${fmt(s.performance_90d)} | ${fmt(s.rs_20d)} | ${fmtS(s.vol_score)} | ${fmtS(s.trend_r2)} | ${fmtS(s.momentum_score)} |\n`;
        });
      }
      setMessages((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = { role: "assistant", content: text };
        return copy;
      });
      onConfigApply?.(stocks);
      onChatResponse?.(text);
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : "请求失败";
      setMessages((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = { role: "assistant", content: `⚠️ ${errMsg}` };
        return copy;
      });
    } finally {
      setActiveStreams((n) => Math.max(0, n - 1));
      setToolStatus(null);
    }
  }, [config, isLoading, setMessages, setShowWelcome, onConfigApply, onChatResponse]);

  return (
    <div className="flex flex-col h-full relative">
      {/* Messages area */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {/* Floating action buttons — top-right of messages area */}
        <div className="sticky top-0 z-10 flex justify-end gap-1 -mb-2">
          <button
            onClick={handleNewConversation}
            className="text-zinc-500 hover:text-zinc-300 transition-colors p-1.5 rounded-lg hover:bg-surface-2/80 backdrop-blur-sm bg-[var(--bg-base,#09090b)]/60"
            title="新对话"
          >
            <MessageSquarePlus className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => setHistoryOpen((v) => !v)}
            className={`text-zinc-500 hover:text-zinc-300 transition-colors p-1.5 rounded-lg hover:bg-surface-2/80 backdrop-blur-sm bg-[var(--bg-base,#09090b)]/60 ${
              historyOpen ? "text-brand" : ""
            }`}
            title="历史对话"
          >
            <History className="w-3.5 h-3.5" />
          </button>
          {onToggleExpand && (
            <button
              onClick={onToggleExpand}
              className="text-zinc-500 hover:text-zinc-300 transition-colors p-1.5 rounded-lg hover:bg-surface-2/80 backdrop-blur-sm bg-[var(--bg-base,#09090b)]/60"
              title={expanded ? "收起" : "展开"}
            >
              {expanded ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
            </button>
          )}
        </div>
        {/* History panel */}
        {historyOpen && (
          <div className="sticky top-8 z-20 mx-1 mb-2 rounded-xl border border-zinc-800 bg-[var(--bg-base,#09090b)]/95 backdrop-blur-md shadow-lg max-h-64 overflow-y-auto">
            {chatHistory.length === 0 ? (
              <p className="text-xs text-theme-muted text-center py-4">暂无历史对话</p>
            ) : (
              <ul className="divide-y divide-zinc-800/60">
                {chatHistory.map((s) => (
                  <li
                    key={s.id}
                    className="flex items-center gap-2 px-3 py-2 hover:bg-zinc-800/40 cursor-pointer group"
                    onClick={() => handleSwitchSession(s.id)}
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-theme-primary truncate">{s.title}</p>
                      <p className="text-[10px] text-theme-muted">
                        {new Date(s.updatedAt).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                        {" · "}{s.messages.length} 条
                      </p>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); deleteSession(s.id); }}
                      className="opacity-0 group-hover:opacity-100 text-zinc-500 hover:text-red-400 transition-all p-0.5"
                      title="删除"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {showWelcome && messages.length === 0 && (
          <div className="flex flex-col items-center justify-center py-8 text-center px-4">
            <div className="w-14 h-14 rounded-2xl bg-brand/10 flex items-center justify-center mb-4">
              <Activity className="w-7 h-7 text-brand" />
            </div>
            <h3 className="text-lg font-semibold text-theme-primary mb-1.5">
              Atlas 智能投研助手
            </h3>
            <p className="text-sm text-theme-muted max-w-[340px] mb-2">
              支持强势股筛选、个股深度分析、同业对比、市场概览
            </p>
            <p className="text-xs text-theme-muted/60 max-w-[320px] mb-6">
              输入任何问题，或点击下方常用指令快速开始
            </p>
            <QuickPrompts onSelect={handleQuickPrompt} />
          </div>
        )}

        {messages.map((msg, i) => {
          const isLast = i === messages.length - 1;
          // A message is "streaming" if it's an empty-content assistant msg while streams are active
          const streaming = msg.role === "assistant" && isLoading && msg.content === "";
          const isLastAssistant = msg.role === "assistant" && isLast && !isLoading && msg.content.length > 0;
          return (
            <div key={i}>
              <MessageBubble message={msg} isStreaming={streaming} />
              {/* Disambiguation picker */}
              {msg.disambiguateOptions && msg.disambiguateOptions.length > 0 && !isLoading && (
                <div className="flex flex-wrap gap-1.5 mt-2 ml-1">
                  {msg.disambiguateOptions.map((t) => (
                    <button
                      key={t}
                      onClick={() => handleDisambiguate(t)}
                      className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-brand/10 border border-brand/20 text-xs font-medium text-brand hover:bg-brand/20 hover:border-brand/30 transition-all duration-200"
                    >
                      {t}
                    </button>
                  ))}
                </div>
              )}
              {isLastAssistant && !msg.disambiguateOptions && (
                <FollowupPrompts onSelect={handleQuickPrompt} disabled={isLoading} />
              )}
            </div>
          );
        })}

        {isLoading && toolStatus && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-brand/5 border border-brand/10 text-xs text-brand animate-fade-in">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-brand animate-pulse" />
            {toolStatus}
          </div>
        )}
      </div>

      {/* Chip bar — read-only config summary above input */}
      <ConfigChipBar config={config} onOpenDrawer={() => setDrawerOpen(true)} onApply={handleApplyConfig} applyLoading={isLoading} />

      {/* Input */}
      <div className="shrink-0 px-4 pb-4 pt-2">
        <PromptInput onSend={handleSend} disabled={false} />
      </div>

      {/* Config drawer — slides from right */}
      <ConfigDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        config={config}
        onConfigChange={setConfig}
        onApply={handleApplyConfig}
      />
    </div>
  );
}
