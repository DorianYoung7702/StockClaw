"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { BookOpen, Bot, Eye, KeyRound, MessageSquare, Sparkles, Target, X } from "lucide-react";
import { useAuth } from "./token-gate";

const AUTO_OPEN_STORAGE_KEY = "atlas_help_autoshown_v1";

interface HelpCenterContextValue {
  isHelpOpen: boolean;
  openHelp: () => void;
  closeHelp: () => void;
  hasAutoOpenedHomeGuide: boolean;
  markAutoOpenedHomeGuide: () => void;
}

const HelpCenterContext = createContext<HelpCenterContextValue>({
  isHelpOpen: false,
  openHelp: () => {},
  closeHelp: () => {},
  hasAutoOpenedHomeGuide: false,
  markAutoOpenedHomeGuide: () => {},
});

export function useHelpCenter() {
  return useContext(HelpCenterContext);
}

const GUIDE_SECTIONS = [
  {
    icon: Sparkles,
    title: "30 秒快速上手",
    items: [
      "首页左侧是对话，右侧是当天强势股候选池。直接问「帮我看看 NVDA」或「今天有什么值得看」即可。",
      "候选列表点任意标的会进入深度分析面板，技术面与基本面并排展示，附带 RAG 证据链。",
      "把感兴趣的票加入观察组，常驻 Agent 会自动按节奏跟踪，不在线也会继续跑。",
    ],
  },
  {
    icon: MessageSquare,
    title: "对话工作台",
    items: [
      "支持自然语言发起任务：强势股筛选、单票深度分析、同业对比、舆情摘要、市场概览都走这里。",
      "对话是 SSE 流式，Agent 在调用哪个工具、拿到了什么数据，实时显示在消息气泡上。",
      "一次可以问复合问题（例如「AAPL 和 MSFT 各做一份简报，对比毛利率」），系统会拆成多任务并行。",
    ],
  },
  {
    icon: Target,
    title: "深度分析报告",
    items: [
      "技术面：价格走势、RSI、成交量、相对强弱、趋势评级，用来判断短期买卖点。",
      "基本面：结构化 JSON 简报 + Markdown 详细报告，包含主要亮点、风险、关键财务指标。",
      "所有结论都附 RAG 证据卡：财报片段 / 新闻事件 / 政策动态，可溯源到原始链接。",
    ],
  },
  {
    icon: Eye,
    title: "观察组与长期记忆",
    items: [
      "观察组支持多市场（美股、A 股、港股、ETF），可批量触发分析并查看跨标的对比。",
      "把观察组打开后，系统会自动把它挂到常驻 Agent，后台按周期生成增量结论卡。",
      "长期记忆页面记录了系统对每只票的持续观察：上一轮结论、变化点、待验证假设。",
    ],
  },
  {
    icon: Bot,
    title: "常驻 Agent（Agent 页）",
    items: [
      "给定一个研究目标（如「NVDA 每周财报追踪」），Agent 会自动按节奏巡检、落结论、做漂移检测。",
      "每一轮 cycle 产出一张结论卡：本轮要点、与上轮差异、KPI 完成情况、异常告警。",
      "观察组添加的票会自动进入 watchlist_review 常驻循环，不需要手动创建任务。",
    ],
  },
  {
    icon: KeyRound,
    title: "登录模式与模型切换",
    items: [
      "「默认进入」走平台预置模型，需要管理员 token；适合快速体验，无需自备 API Key。",
      "「自带模型」支持 OpenAI 兼容 / DeepSeek / MiniMax / 智谱 GLM，填入你自己的 API Key 即可使用独立会话。",
      "登录后可在设置页随时切换模型、调整数据源优先级、管理 Token，配置按用户隔离。",
    ],
  },
  {
    icon: BookOpen,
    title: "RAG 证据链怎么看",
    items: [
      "财报切片：来自 10-K / 10-Q / MD&A，用来支撑长期基本面判断（业务结构、风险因素、管理层讨论）。",
      "新闻事件：覆盖近期催化、政策动态、突发事件，用来解释价格与情绪的变化。",
      "每张证据卡都显示来源、片段、相关度分数、时间戳与原文链接，方便复核结论依据。",
    ],
  },
  {
    icon: Sparkles,
    title: "小贴士",
    items: [
      "首次使用建议：先在对话里问「今天美股有什么值得看」，再从候选池挑一只点深度分析。",
      "分析结果会缓存到当前会话，页面切换不会丢；切换模型或退出登录会重置。",
      "关闭本说明后，随时点左上角 Logo 可以再次打开。更多介绍见 GitHub 仓库 StockClaw。",
    ],
  },
] as const;

function HelpCenterModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[120] flex items-end justify-center p-0 sm:items-center sm:p-6">
      <button
        aria-label="关闭说明文档遮罩"
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative w-full max-w-5xl max-h-[92dvh] overflow-hidden rounded-t-3xl border border-zinc-800/70 bg-[var(--surface-0)] shadow-2xl shadow-black/40 sm:max-h-[88vh] sm:rounded-3xl">
        <div className="flex items-start justify-between gap-4 border-b border-zinc-800/60 px-4 py-4 sm:px-6 sm:py-5">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-brand/10 px-3 py-1 text-[11px] font-medium text-brand mb-3">
              <BookOpen className="h-3.5 w-3.5" />
              快速使用说明
            </div>
            <h2 className="text-xl sm:text-2xl font-semibold text-zinc-100">StockClaw 智能投研平台 · 使用指南</h2>
            <p className="mt-2 text-sm leading-6 text-zinc-400 max-w-3xl pr-2">
              对话驱动的多 Agent 研究平台，基于 LangGraph 编排，内建 Harness 工程中间层负责可靠性与长期自治。
              这份指南带你快速熟悉：对话工作台、深度分析、观察组与长期记忆、常驻 Agent、登录模式与模型切换。
              <br className="hidden sm:inline" />
              <span className="text-zinc-500">关闭后随时点左上角 Logo 可再次打开。</span>
            </p>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 rounded-xl border border-zinc-800/70 bg-surface-1 p-2 text-zinc-400 transition-colors hover:text-zinc-200 hover:bg-surface-2"
            aria-label="关闭说明文档"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="max-h-[calc(92dvh-88px)] overflow-y-auto px-4 py-4 sm:max-h-[calc(88vh-96px)] sm:px-6 sm:py-6">
          <div className="grid gap-4 lg:grid-cols-2">
            {GUIDE_SECTIONS.map((section) => {
              const Icon = section.icon;
              return (
                <section key={section.title} className="rounded-2xl border border-zinc-800/50 bg-surface-1/70 p-4 sm:p-5">
                  <div className="flex items-center gap-3 mb-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand/10 text-brand">
                      <Icon className="h-5 w-5" />
                    </div>
                    <h3 className="text-base font-semibold text-zinc-100">{section.title}</h3>
                  </div>
                  <div className="space-y-2.5">
                    {section.items.map((item) => (
                      <div key={item} className="flex items-start gap-2.5 text-sm leading-6 text-zinc-300">
                        <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-brand/70" />
                        <span>{item}</span>
                      </div>
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

export function HelpCenterProvider({ children }: { children: ReactNode }) {
  const { triggerBeam } = useAuth();
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const [hasAutoOpenedHomeGuide, setHasAutoOpenedHomeGuide] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    setHasAutoOpenedHomeGuide(window.sessionStorage.getItem(AUTO_OPEN_STORAGE_KEY) === "1");
  }, []);

  const openHelp = useCallback(() => {
    setIsHelpOpen(true);
  }, []);

  const closeHelp = useCallback(() => {
    setIsHelpOpen(false);
    triggerBeam();
  }, [triggerBeam]);

  const markAutoOpenedHomeGuide = useCallback(() => {
    setHasAutoOpenedHomeGuide(true);
    if (typeof window !== "undefined") {
      window.sessionStorage.setItem(AUTO_OPEN_STORAGE_KEY, "1");
    }
  }, []);

  const value = useMemo<HelpCenterContextValue>(() => ({
    isHelpOpen,
    openHelp,
    closeHelp,
    hasAutoOpenedHomeGuide,
    markAutoOpenedHomeGuide,
  }), [isHelpOpen, openHelp, closeHelp, hasAutoOpenedHomeGuide, markAutoOpenedHomeGuide]);

  return (
    <HelpCenterContext.Provider value={value}>
      {children}
      <HelpCenterModal open={isHelpOpen} onClose={closeHelp} />
    </HelpCenterContext.Provider>
  );
}
