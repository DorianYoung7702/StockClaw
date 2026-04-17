"use client";

import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Clock,
  Eye,
  Loader2,
  Play,
  Power,
  RefreshCw,
  Settings2,
} from "lucide-react";
import { cleanLLMOutput, cn } from "@/lib/utils";
import {
  getHarnessDashboard,
  getResidentAgentStatus,
  runResidentAgentOnce,
  updateResidentAgentStatus,
  type ResidentAgentStatus,
} from "@/lib/api";
import { useUserId } from "@/lib/use-user-id";

const INTERVAL_OPTIONS = [
  { value: 300, label: "5 分钟" },
  { value: 900, label: "15 分钟" },
  { value: 1800, label: "30 分钟" },
  { value: 3600, label: "1 小时" },
  { value: 14400, label: "4 小时" },
];

function fmtTime(ts?: number) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function plainPreview(text?: string, max = 140) {
  if (!text) return "";
  const cleaned = cleanLLMOutput(text)
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/[>#*_`\-]+/g, " ")
    .replace(/\[(.*?)\]\((.*?)\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
  if (cleaned.length <= max) return cleaned;
  return `${cleaned.slice(0, max).trim()}…`;
}

export function ResidentAgentConsole() {
  const userId = useUserId();
  const [status, setStatus] = useState<ResidentAgentStatus | null>(null);
  const [dashboard, setDashboard] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [intervalSeconds, setIntervalSeconds] = useState(900);

  const loadStatus = useCallback(async (silent = false) => {
    if (!userId) return;
    if (!silent) setLoading(true);
    try {
      const data = await getResidentAgentStatus(userId);
      setStatus(data);
      setIntervalSeconds(data.interval_seconds || 900);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载常驻 Agent 状态失败");
    } finally {
      if (!silent) setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    getHarnessDashboard().then(setDashboard).catch(() => {});
  }, []);

  useEffect(() => {
    if (!status?.enabled && !status?.running) return;
    const timer = window.setInterval(() => {
      loadStatus(true);
    }, 15000);
    return () => window.clearInterval(timer);
  }, [status?.enabled, status?.running, loadStatus]);

  const handleToggle = useCallback(async () => {
    if (!userId) return;
    setSaving(true);
    try {
      const data = await updateResidentAgentStatus(userId, {
        enabled: !(status?.enabled ?? false),
        interval_seconds: intervalSeconds,
        run_immediately: true,
      });
      setStatus(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "更新常驻 Agent 失败");
    } finally {
      setSaving(false);
    }
  }, [userId, status?.enabled, intervalSeconds]);

  const handleSaveInterval = useCallback(async () => {
    if (!userId || !status) return;
    setSaving(true);
    try {
      const data = await updateResidentAgentStatus(userId, {
        interval_seconds: intervalSeconds,
        run_immediately: false,
      });
      setStatus(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存巡检频率失败");
    } finally {
      setSaving(false);
    }
  }, [userId, status, intervalSeconds]);

  const handleRunNow = useCallback(async () => {
    if (!userId) return;
    setRunning(true);
    try {
      const data = await runResidentAgentOnce(userId);
      setStatus(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "手动执行失败");
    } finally {
      setRunning(false);
    }
  }, [userId]);

  const statusTone = useMemo(() => {
    if (!status) return { label: "未初始化", cls: "bg-zinc-500/15 text-zinc-400", icon: Bot };
    if (status.running) return { label: "巡检中", cls: "bg-brand/15 text-brand", icon: Loader2 };
    if (status.status === "error") return { label: "异常", cls: "bg-red-500/15 text-red-400", icon: AlertTriangle };
    if (status.status === "waiting_watchlist") return { label: "等待观察组", cls: "bg-yellow-500/15 text-yellow-400", icon: AlertTriangle };
    if (status.enabled) return { label: "常驻中", cls: "bg-emerald-500/15 text-emerald-400", icon: CheckCircle2 };
    return { label: "已关闭", cls: "bg-zinc-500/15 text-zinc-400", icon: Power };
  }, [status]);

  const StatusIcon = statusTone.icon;
  const latest = status?.latest_cycle ?? null;
  const latestProduct = latest?.product_summary;
  const latestWatchlistSummary = latestProduct?.watchlist ?? null;
  const latestSymbols = latestProduct?.symbols ?? [];

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto p-4 sm:p-6 space-y-6">
        <div className="rounded-2xl border border-zinc-800/50 bg-surface-1 p-5 sm:p-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Bot className="w-5 h-5 text-brand" />
                <h1 className="text-lg sm:text-xl font-semibold text-zinc-100">常驻投研 Agent</h1>
                <span className={cn("px-2 py-0.5 rounded-full text-[11px] font-medium inline-flex items-center gap-1", statusTone.cls)}>
                  <StatusIcon className={cn("w-3 h-3", status?.running ? "animate-spin" : "")} />
                  {statusTone.label}
                </span>
              </div>
              <p className="text-sm text-zinc-400 max-w-2xl leading-6">
                开启后，Agent 不再依赖单个任务启动，而是后台常驻巡检你的观察组，持续做基本面/事件回看，并把结果沉淀为最近巡检记录。
              </p>
              <div className="flex flex-wrap gap-2 text-xs text-zinc-500">
                <span className="inline-flex items-center gap-1 rounded-lg bg-surface-2 px-2.5 py-1">
                  <Eye className="w-3 h-3" />
                  观察组 {status?.watchlist_count ?? 0} 只
                </span>
                <span className="inline-flex items-center gap-1 rounded-lg bg-surface-2 px-2.5 py-1">
                  <Clock className="w-3 h-3" />
                  上次巡检 {fmtTime(status?.last_run_at)}
                </span>
                <span className="inline-flex items-center gap-1 rounded-lg bg-surface-2 px-2.5 py-1">
                  <Activity className="w-3 h-3" />
                  最近状态 {status?.status || "stopped"}
                </span>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={() => loadStatus()}
                disabled={loading}
                className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-surface-2 text-zinc-300 hover:bg-surface-3 transition disabled:opacity-50"
              >
                <RefreshCw className={cn("w-4 h-4", loading ? "animate-spin" : "")} />
                刷新
              </button>
              <button
                onClick={handleRunNow}
                disabled={running || !status?.watchlist_count}
                className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-brand/15 text-brand hover:bg-brand/25 transition disabled:opacity-40"
              >
                {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                立即巡检
              </button>
              <button
                onClick={handleToggle}
                disabled={saving}
                className={cn(
                  "inline-flex items-center gap-2 px-4 py-2 rounded-xl text-white transition disabled:opacity-50",
                  status?.enabled ? "bg-red-500/80 hover:bg-red-500" : "bg-emerald-600 hover:bg-emerald-500"
                )}
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Power className="w-4 h-4" />}
                {status?.enabled ? "关闭常驻模式" : "开启常驻模式"}
              </button>
            </div>
          </div>

          {error && <div className="mt-4 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300">{error}</div>}
          {!!status?.last_error && <div className="mt-4 rounded-xl border border-yellow-500/20 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-200">最近错误：{status.last_error}</div>}
          {!status?.watchlist_count && <div className="mt-4 rounded-xl border border-zinc-800/60 bg-surface-2 px-4 py-3 text-sm text-zinc-400">当前观察组为空。先去 <Link href="/watchlist" className="text-brand hover:underline">观察页</Link> 添加标的，常驻 Agent 才会开始持续投研。</div>}
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-[1.1fr_0.9fr] gap-6">
          <div className="rounded-2xl border border-zinc-800/50 bg-surface-1 p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Settings2 className="w-4 h-4 text-zinc-500" />
                <h2 className="text-sm font-medium text-zinc-200">常驻设置</h2>
              </div>
              <Link href="/watchlist" className="text-xs text-brand hover:underline">打开观察页</Link>
            </div>

            <div>
              <label className="block text-xs text-zinc-500 mb-2">巡检频率</label>
              <div className="flex flex-col sm:flex-row gap-2">
                <select
                  value={intervalSeconds}
                  onChange={(e) => setIntervalSeconds(Number(e.target.value))}
                  className="flex-1 px-3 py-2 rounded-xl bg-surface-2 border border-zinc-800/50 text-sm text-zinc-200"
                >
                  {INTERVAL_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
                <button
                  onClick={handleSaveInterval}
                  disabled={saving || !status}
                  className="px-4 py-2 rounded-xl bg-surface-2 text-zinc-200 hover:bg-surface-3 transition disabled:opacity-40"
                >
                  保存
                </button>
              </div>
            </div>

            <div>
              <div className="text-xs text-zinc-500 mb-2">当前观察标的</div>
              {status?.watchlist?.length ? (
                <div className="flex flex-wrap gap-2">
                  {status.watchlist.map((item) => (
                    <span key={item.ticker} className="px-2 py-1 rounded-lg bg-brand/10 border border-brand/20 text-xs font-mono text-brand">
                      {item.ticker}
                    </span>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-zinc-500">暂无观察标的</div>
              )}
            </div>

            {dashboard && (
              <div className="grid grid-cols-3 gap-3 pt-2 border-t border-zinc-800/50">
                <div className="rounded-xl bg-surface-2 p-3 text-center">
                  <div className="text-sm font-medium text-zinc-100">{String((dashboard.first_completion_rate as Record<string, unknown>)?.total_runs ?? "—")}</div>
                  <div className="text-[11px] text-zinc-500 mt-1">总运行</div>
                </div>
                <div className="rounded-xl bg-surface-2 p-3 text-center">
                  <div className="text-sm font-medium text-zinc-100">
                    {(dashboard.recovery as Record<string, unknown>)?.auto_recovery_rate != null
                      ? `${Math.round(Number((dashboard.recovery as Record<string, unknown>).auto_recovery_rate) * 100)}%`
                      : "—"}
                  </div>
                  <div className="text-[11px] text-zinc-500 mt-1">恢复率</div>
                </div>
                <div className="rounded-xl bg-surface-2 p-3 text-center">
                  <div className="text-sm font-medium text-zinc-100">
                    {(dashboard.quality_scores as Record<string, unknown>)?.mean
                      ? Number((dashboard.quality_scores as Record<string, unknown>).mean).toFixed(1)
                      : "—"}
                  </div>
                  <div className="text-[11px] text-zinc-500 mt-1">平均质量</div>
                </div>
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-zinc-800/50 bg-surface-1 p-5 space-y-4">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-zinc-500" />
              <h2 className="text-sm font-medium text-zinc-200">最新巡检摘要</h2>
            </div>
            {!latest ? (
              <div className="text-sm text-zinc-500 py-10 text-center">还没有巡检记录。开启常驻模式或点击“立即巡检”开始第一轮。</div>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className={cn(
                    "px-2 py-0.5 rounded-full",
                    latest.status === "success" ? "bg-emerald-500/15 text-emerald-400" : latest.status === "partial" ? "bg-yellow-500/15 text-yellow-400" : "bg-red-500/15 text-red-400"
                  )}>
                    {latest.status}
                  </span>
                  <span className="text-zinc-500">{fmtTime(latest.started_at)}</span>
                  {latest.quality_score != null && <span className="text-zinc-400">质量 {Number(latest.quality_score).toFixed(1)}</span>}
                </div>
                {latestWatchlistSummary && (
                  <div className="rounded-2xl border border-brand/20 bg-brand/5 p-4 space-y-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="px-2 py-0.5 rounded-full bg-zinc-800 text-xs text-zinc-300">
                        总体 {latestWatchlistSummary.overall_stance || "neutral"}
                      </span>
                      <span className="px-2 py-0.5 rounded-full bg-zinc-800 text-xs text-zinc-300">
                        置信度 {latestWatchlistSummary.confidence || "—"}
                      </span>
                      {latestWatchlistSummary.major_change_count != null && (
                        <span className="px-2 py-0.5 rounded-full bg-zinc-800 text-xs text-zinc-300">
                          显著变化 {latestWatchlistSummary.major_change_count} 只
                        </span>
                      )}
                    </div>
                    <div className="text-sm text-zinc-100 leading-6">{latestWatchlistSummary.headline || "本轮暂无总体结论"}</div>
                    <div className="grid grid-cols-1 gap-2 text-xs text-zinc-400 sm:grid-cols-2">
                      <div className="rounded-xl bg-surface-2 px-3 py-2">
                        <div className="text-zinc-500 mb-1">需要关注</div>
                        <div>{latestWatchlistSummary.symbols_requiring_attention?.join("、") || "暂无"}</div>
                      </div>
                      <div className="rounded-xl bg-surface-2 px-3 py-2">
                        <div className="text-zinc-500 mb-1">相对稳定</div>
                        <div>{latestWatchlistSummary.stable_symbols?.join("、") || "暂无"}</div>
                      </div>
                    </div>
                  </div>
                )}
                {!!latestSymbols.length && (
                  <div className="space-y-3">
                    {latestSymbols.slice(0, 6).map((item) => (
                      <div key={item.ticker} className="rounded-xl border border-zinc-800/40 bg-surface-2 p-4 space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-mono text-zinc-100">{item.ticker}</span>
                          {item.stance && (
                            <span className="px-2 py-0.5 rounded-full bg-zinc-800 text-[11px] text-zinc-300">
                              {item.stance}
                            </span>
                          )}
                          {item.change_severity && (
                            <span className="px-2 py-0.5 rounded-full bg-zinc-800 text-[11px] text-zinc-300">
                              {item.change_severity}
                            </span>
                          )}
                          {item.conclusion?.confidence && (
                            <span className="px-2 py-0.5 rounded-full bg-zinc-800 text-[11px] text-zinc-300">
                              置信度 {item.conclusion.confidence}
                            </span>
                          )}
                        </div>
                        <div className="text-sm text-zinc-200 leading-6">{item.conclusion?.summary || item.conclusion?.title || "暂无结论摘要"}</div>
                        {item.conclusion?.why && <div className="text-xs text-zinc-400">原因：{item.conclusion.why}</div>}
                        {!!item.conclusion?.changes?.length && (
                          <div className="text-xs text-zinc-400">变化：{item.conclusion.changes[0]}</div>
                        )}
                        {item.conclusion?.top_risk && <div className="text-xs text-yellow-300">风险：{item.conclusion.top_risk}</div>}
                      </div>
                    ))}
                  </div>
                )}
                <div className="rounded-xl bg-surface-2 border border-zinc-800/40 p-4 max-h-[320px] overflow-y-auto">
                  <div className="prose prose-sm prose-zinc dark:prose-invert max-w-none text-zinc-300 leading-6">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {cleanLLMOutput(latest.report_markdown || "本轮未返回摘要。")}
                    </ReactMarkdown>
                  </div>
                </div>
                {!!latest.errors?.length && (
                  <div className="rounded-xl border border-yellow-500/20 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-100">
                    {latest.errors.join("；")}
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-zinc-800/50 bg-surface-1 p-5">
          <div className="flex items-center gap-2 mb-4">
            <Clock className="w-4 h-4 text-zinc-500" />
            <h2 className="text-sm font-medium text-zinc-200">最近巡检历史</h2>
          </div>
          {!status?.recent_cycles?.length ? (
            <div className="text-sm text-zinc-500 text-center py-6">暂无历史记录</div>
          ) : (
            <div className="space-y-2">
              {status.recent_cycles.map((cycle) => (
                <div key={cycle.cycle_id} className="flex items-start gap-3 rounded-xl border border-zinc-800/40 bg-surface-2 px-4 py-3">
                  <div className={cn(
                    "mt-0.5 w-8 h-8 rounded-full flex items-center justify-center shrink-0",
                    cycle.status === "success" ? "bg-emerald-500/10" : cycle.status === "partial" ? "bg-yellow-500/10" : "bg-red-500/10"
                  )}>
                    {cycle.status === "success"
                      ? <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      : <AlertTriangle className={cn("w-4 h-4", cycle.status === "partial" ? "text-yellow-400" : "text-red-400")} />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="text-zinc-100 font-mono">#{cycle.cycle_id.slice(-6)}</span>
                      <span className="text-zinc-500">{fmtTime(cycle.started_at)}</span>
                      {cycle.quality_score != null && <span className="text-zinc-400">质量 {Number(cycle.quality_score).toFixed(1)}</span>}
                    </div>
                    {cycle.report_markdown && <p className="mt-1 text-sm text-zinc-400 line-clamp-2">{plainPreview(cycle.report_markdown)}</p>}
                    {!!cycle.errors?.length && <p className="mt-1 text-xs text-yellow-300">{cycle.errors.join("；")}</p>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
