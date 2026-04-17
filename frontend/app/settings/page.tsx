"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Settings2,
  Key,
  Eye,
  EyeOff,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  ExternalLink,
  Save,
  Zap,
  Construction,
  Globe,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  listDataSources,
  listLLMProviders,
  getDataSourceConfig,
  getLLMConfig,
  updateDataSourceConfig,
  updateLLMConfig,
  deleteLLMConfig,
  testDataSource,
  testLLMConfig,
  type DataSourceProviderInfo,
  type DataSourceConfigItem,
  type LLMProviderInfo,
} from "@/lib/api";
import { useUserId } from "@/lib/use-user-id";

/* ── Category metadata ───────────────────────────────────────────────── */

const CATEGORIES = [
  { key: "fundamental", label: "基本面", color: "text-blue-400" },
  { key: "news", label: "新闻", color: "text-emerald-400" },
  { key: "market", label: "行情", color: "text-amber-400" },
  { key: "macro", label: "宏观", color: "text-purple-400" },
] as const;

const CATEGORY_BADGE: Record<string, { bg: string; text: string }> = {
  fundamental: { bg: "bg-blue-500/15", text: "text-blue-400" },
  news: { bg: "bg-emerald-500/15", text: "text-emerald-400" },
  market: { bg: "bg-amber-500/15", text: "text-amber-400" },
  macro: { bg: "bg-purple-500/15", text: "text-purple-400" },
};

/* ── Types ────────────────────────────────────────────────────────── */

interface ProviderState {
  meta: DataSourceProviderInfo;
  config: DataSourceConfigItem | null;
  apiKeyInput: string;
  showKey: boolean;
  enabled: boolean;
  priorityOverrides: Record<string, number>;
  testStatus: "idle" | "testing" | "success" | "fail";
  testMessage: string;
  testLatency?: number;
  dirty: boolean;
  expanded: boolean;
}

interface LLMState {
  provider: string;
  displayName: string;
  apiKeyInput: string;
  apiKeyMasked: string;
  hasKey: boolean;
  showKey: boolean;
  baseUrl: string;
  toolCallingModel: string;
  reasoningModel: string;
  toolCallingTemperature: string;
  reasoningTemperature: string;
  maxTokens: string;
  enabled: boolean;
  source: string;
  supportsCustomBaseUrl: boolean;
  dirty: boolean;
  testStatus: "idle" | "testing" | "success" | "fail";
  testMessage: string;
  testLatency?: number;
}

/* ── Page ─────────────────────────────────────────────────────────── */

export default function SettingsPage() {
  const userId = useUserId();
  const [providers, setProviders] = useState<ProviderState[]>([]);
  const [llmProviders, setLlmProviders] = useState<LLMProviderInfo[]>([]);
  const [llmState, setLlmState] = useState<LLMState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [filterCat, setFilterCat] = useState<string>("all");
  const [showGlobal, setShowGlobal] = useState(false);

  /* ── Load data ──────────────────────────────────────────────────── */

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      const effectiveUserId = showGlobal ? "__global__" : userId;
      const [defRes, cfgRes, llmDefRes, llmCfgRes] = await Promise.all([
        listDataSources(),
        getDataSourceConfig(effectiveUserId),
        listLLMProviders(),
        getLLMConfig(effectiveUserId),
      ]);

      const configMap = new Map<string, DataSourceConfigItem>();
      for (const c of cfgRes.configs) configMap.set(c.provider_name, c);

      setProviders(
        defRes.providers.map((meta) => {
          const cfg = configMap.get(meta.name) ?? null;
          return {
            meta,
            config: cfg,
            apiKeyInput: "",
            showKey: false,
            enabled: cfg?.enabled ?? true,
            priorityOverrides: cfg?.priority_overrides ?? {},
            testStatus: "idle",
            testMessage: "",
            dirty: false,
            expanded: false,
          };
        })
      );

      setLlmProviders(llmDefRes.providers);
      const llmCfg = llmCfgRes.config;
      setLlmState({
        provider: llmCfg.provider,
        displayName: llmCfg.display_name,
        apiKeyInput: "",
        apiKeyMasked: llmCfg.api_key_masked,
        hasKey: llmCfg.has_key,
        showKey: false,
        baseUrl: llmCfg.base_url || "",
        toolCallingModel: llmCfg.tool_calling_model,
        reasoningModel: llmCfg.reasoning_model,
        toolCallingTemperature: String(llmCfg.tool_calling_temperature),
        reasoningTemperature: String(llmCfg.reasoning_temperature),
        maxTokens: String(llmCfg.max_tokens),
        enabled: llmCfg.enabled,
        source: llmCfg.source,
        supportsCustomBaseUrl: llmCfg.supports_custom_base_url,
        dirty: false,
        testStatus: "idle",
        testMessage: "",
      });
    } catch (e) {
      console.error("Failed to load datasource config:", e);
    } finally {
      setLoading(false);
    }
  }, [userId, showGlobal]);

  useEffect(() => {
    if (userId) loadData();
  }, [userId, loadData]);

  /* ── Mutations ──────────────────────────────────────────────────── */

  const update = (idx: number, patch: Partial<ProviderState>, markDirty = true) => {
    setProviders((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], ...patch, dirty: markDirty ? true : next[idx].dirty };
      return next;
    });
    if (markDirty) setSaveMsg(null);
  };

  const updateLlm = (patch: Partial<LLMState>, markDirty = true) => {
    setLlmState((prev) => {
      if (!prev) return prev;
      return { ...prev, ...patch, dirty: markDirty ? true : prev.dirty };
    });
    if (markDirty) setSaveMsg(null);
  };

  const handleTest = async (idx: number) => {
    const p = providers[idx];
    update(idx, { testStatus: "testing", testMessage: "" }, false);
    try {
      const res = await testDataSource(p.meta.name, p.apiKeyInput || "");
      setProviders((prev) => {
        const next = [...prev];
        next[idx] = {
          ...next[idx],
          testStatus: res.success ? "success" : "fail",
          testMessage: res.message,
          testLatency: res.latency_ms,
        };
        return next;
      });
    } catch (e: unknown) {
      setProviders((prev) => {
        const next = [...prev];
        next[idx] = {
          ...next[idx],
          testStatus: "fail",
          testMessage: e instanceof Error ? e.message : "Unknown error",
        };
        return next;
      });
    }
  };

  const handleTestLlm = async () => {
    if (!llmState) return;
    const selectedMeta = llmProviders.find((item) => item.name === llmState.provider);
    const apiKey = llmState.apiKeyInput.trim();
    if (!apiKey) {
      updateLlm({ testStatus: "fail", testMessage: llmState.hasKey ? "已保存密钥不会回传，请重新输入后测试" : "请输入 API Key 后再测试" }, false);
      return;
    }
    updateLlm({ testStatus: "testing", testMessage: "", testLatency: undefined }, false);
    try {
      const res = await testLLMConfig({
        provider: llmState.provider,
        api_key: apiKey,
        base_url: llmState.supportsCustomBaseUrl ? (llmState.baseUrl.trim() || null) : null,
        tool_calling_model: llmState.toolCallingModel || selectedMeta?.default_tool_model || null,
        reasoning_model: llmState.reasoningModel || selectedMeta?.default_reasoning_model || null,
        tool_calling_temperature: Number(llmState.toolCallingTemperature || 0),
        reasoning_temperature: Number(llmState.reasoningTemperature || 0.3),
        max_tokens: Number(llmState.maxTokens || 4096),
      });
      updateLlm({ testStatus: res.success ? "success" : "fail", testMessage: res.message, testLatency: res.latency_ms }, false);
    } catch (e: unknown) {
      updateLlm({ testStatus: "fail", testMessage: e instanceof Error ? e.message : "Unknown error" }, false);
    }
  };

  const handleResetLlm = async () => {
    const effectiveUserId = showGlobal ? "__global__" : userId;
    if (!effectiveUserId) return;
    try {
      await deleteLLMConfig(effectiveUserId);
      await loadData();
      setSaveMsg({ ok: true, text: "已恢复为系统默认模型配置" });
    } catch (e: unknown) {
      setSaveMsg({ ok: false, text: e instanceof Error ? e.message : "恢复默认失败" });
    }
  };

  const handleSave = async () => {
    const dirtyItems = providers.filter((p) => p.dirty);
    const llmDirty = !!llmState?.dirty;
    if (!dirtyItems.length && !llmDirty) return;

    setSaving(true);
    setSaveMsg(null);
    try {
      const effectiveUserId = showGlobal ? "__global__" : userId;
      const savedParts: string[] = [];
      const configs = dirtyItems.map((p) => ({
        provider_name: p.meta.name,
        api_key: p.apiKeyInput || null,
        enabled: p.enabled,
        priority_overrides: Object.keys(p.priorityOverrides).length > 0 ? p.priorityOverrides : undefined,
      }));
      if (configs.length > 0) {
        await updateDataSourceConfig(effectiveUserId, configs);
        savedParts.push(`${configs.length} 个数据源配置`);
      }
      if (llmDirty && llmState) {
        await updateLLMConfig(effectiveUserId, {
          provider: llmState.provider,
          api_key: llmState.apiKeyInput.trim() ? llmState.apiKeyInput.trim() : null,
          base_url: llmState.supportsCustomBaseUrl ? (llmState.baseUrl.trim() || null) : null,
          tool_calling_model: llmState.toolCallingModel.trim() || null,
          reasoning_model: llmState.reasoningModel.trim() || null,
          tool_calling_temperature: Number(llmState.toolCallingTemperature || 0),
          reasoning_temperature: Number(llmState.reasoningTemperature || 0.3),
          max_tokens: Number(llmState.maxTokens || 4096),
          enabled: llmState.enabled,
        });
        savedParts.push("模型配置");
      }
      setSaveMsg({ ok: true, text: `已保存 ${savedParts.join(" + ")}` });
      setProviders((prev) => prev.map((p) => ({ ...p, dirty: false, apiKeyInput: "" })));
      await loadData();
    } catch (e: unknown) {
      setSaveMsg({ ok: false, text: e instanceof Error ? e.message : "保存失败" });
    } finally {
      setSaving(false);
    }
  };

  /* ── Filter ─────────────────────────────────────────────────────── */

  const filtered = filterCat === "all"
    ? providers
    : providers.filter((p) => p.meta.categories.includes(filterCat));

  const dirtyCount = providers.filter((p) => p.dirty).length + (llmState?.dirty ? 1 : 0);

  /* ── Render ─────────────────────────────────────────────────────── */

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-brand" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto px-4 py-6 sm:px-6 sm:py-8 space-y-6">
        {/* Header */}
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Settings2 className="w-6 h-6 text-brand" />
              数据源与模型配置
            </h1>
            <p className="text-sm text-zinc-400 mt-1">
              管理大模型 API、财经数据源 API Key、启用状态与优先级
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {/* Global / User toggle */}
            <button
              onClick={() => setShowGlobal(!showGlobal)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                showGlobal
                  ? "bg-amber-500/15 text-amber-400 border border-amber-500/30"
                  : "bg-surface-2 text-zinc-400 hover:text-zinc-300"
              )}
            >
              <Globe className="w-3.5 h-3.5" />
              {showGlobal ? "全局模式" : "个人模式"}
            </button>
            {/* Save button */}
            <button
              onClick={handleSave}
              disabled={!dirtyCount || saving}
              className={cn(
                "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all",
                dirtyCount
                  ? "bg-brand text-white hover:bg-brand/90"
                  : "bg-surface-2 text-zinc-500 cursor-not-allowed"
              )}
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              保存{dirtyCount > 0 && ` (${dirtyCount})`}
            </button>
          </div>
        </div>

        {/* Save message */}
        {saveMsg && (
          <div className={cn(
            "px-4 py-2 rounded-lg text-sm flex items-center gap-2",
            saveMsg.ok ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400"
          )}>
            {saveMsg.ok ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
            {saveMsg.text}
          </div>
        )}

        {llmState && (
          <div className="rounded-2xl border border-surface-2 bg-surface-1 p-4 sm:p-5 space-y-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h2 className="text-base font-semibold text-theme-primary flex items-center gap-2">
                  <Zap className="w-4 h-4 text-brand" />
                  大模型配置
                </h2>
                <p className="text-xs text-zinc-500 mt-1 leading-6">
                  可覆盖系统默认模型，支持用户填写自己的 API Key 直连。当前来源：{llmState.source || "default"}。
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {(llmState.source === "user" || llmState.source === "global") && (
                  <button
                    onClick={handleResetLlm}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-2 text-zinc-300 hover:bg-surface-3 transition-all"
                  >
                    恢复默认
                  </button>
                )}
                <button
                  onClick={handleTestLlm}
                  disabled={llmState.testStatus === "testing"}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-2 text-zinc-300 hover:bg-surface-3 transition-all disabled:opacity-60"
                >
                  {llmState.testStatus === "testing" ? "测试中..." : "测试模型"}
                </button>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label className="text-xs text-zinc-400">模型提供方</label>
                <select
                  value={llmState.provider}
                  onChange={(e) => {
                    const nextProvider = e.target.value;
                    const meta = llmProviders.find((item) => item.name === nextProvider);
                    updateLlm({
                      provider: nextProvider,
                      displayName: meta?.display_name || nextProvider,
                      supportsCustomBaseUrl: !!meta?.supports_custom_base_url,
                      baseUrl: meta?.supports_custom_base_url ? llmState.baseUrl : "",
                      toolCallingModel: meta?.default_tool_model || llmState.toolCallingModel,
                      reasoningModel: meta?.default_reasoning_model || llmState.reasoningModel,
                    });
                  }}
                  className="w-full px-3 py-2 rounded-lg bg-surface-2 text-sm text-zinc-200 border border-zinc-800/50 focus:border-brand/50 focus:outline-none"
                >
                  {llmProviders.map((item) => (
                    <option key={item.name} value={item.name}>{item.display_name}</option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-400">启用</label>
                <button
                  type="button"
                  onClick={() => updateLlm({ enabled: !llmState.enabled })}
                  aria-pressed={llmState.enabled}
                  className={cn(
                    "relative h-10 w-20 rounded-full transition-colors",
                    llmState.enabled ? "bg-brand" : "bg-zinc-600"
                  )}
                >
                  <span
                    className={cn(
                      "absolute left-1 top-1 h-8 w-8 rounded-full bg-white transition-transform",
                      llmState.enabled ? "translate-x-10" : "translate-x-0"
                    )}
                  />
                </button>
              </div>

              <div className="space-y-1.5 sm:col-span-2">
                <label className="text-xs text-zinc-400 flex items-center gap-1">
                  <Key className="w-3 h-3" />
                  API Key
                  {llmState.hasKey && <span className="text-zinc-500 ml-1">({llmState.apiKeyMasked})</span>}
                </label>
                <div className="relative">
                  <input
                    type={llmState.showKey ? "text" : "password"}
                    value={llmState.apiKeyInput}
                    onChange={(e) => updateLlm({ apiKeyInput: e.target.value })}
                    placeholder={llmState.hasKey ? "留空保持不变，重新输入可覆盖" : "输入你的模型 API Key"}
                    className="w-full px-3 py-2 rounded-lg bg-surface-2 border border-surface-3 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-brand/50"
                  />
                  <button
                    onClick={() => updateLlm({ showKey: !llmState.showKey }, false)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                  >
                    {llmState.showKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  </button>
                </div>
              </div>

              {llmState.supportsCustomBaseUrl && (
                <div className="space-y-1.5 sm:col-span-2">
                  <label className="text-xs text-zinc-400">Base URL</label>
                  <input
                    value={llmState.baseUrl}
                    onChange={(e) => updateLlm({ baseUrl: e.target.value })}
                    placeholder="如 https://api.openai.com/v1"
                    className="w-full px-3 py-2 rounded-lg bg-surface-2 border border-surface-3 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-brand/50"
                  />
                </div>
              )}

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-400">工具调用模型</label>
                <input
                  value={llmState.toolCallingModel}
                  onChange={(e) => updateLlm({ toolCallingModel: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-surface-2 border border-surface-3 text-sm text-zinc-200 focus:outline-none focus:border-brand/50"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-400">推理模型</label>
                <input
                  value={llmState.reasoningModel}
                  onChange={(e) => updateLlm({ reasoningModel: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-surface-2 border border-surface-3 text-sm text-zinc-200 focus:outline-none focus:border-brand/50"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-400">工具温度</label>
                <input
                  type="number"
                  min={0}
                  max={2}
                  step={0.1}
                  value={llmState.toolCallingTemperature}
                  onChange={(e) => updateLlm({ toolCallingTemperature: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-surface-2 border border-surface-3 text-sm text-zinc-200 focus:outline-none focus:border-brand/50"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-400">推理温度</label>
                <input
                  type="number"
                  min={0}
                  max={2}
                  step={0.1}
                  value={llmState.reasoningTemperature}
                  onChange={(e) => updateLlm({ reasoningTemperature: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-surface-2 border border-surface-3 text-sm text-zinc-200 focus:outline-none focus:border-brand/50"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-400">Max Tokens</label>
                <input
                  type="number"
                  min={128}
                  max={32768}
                  step={128}
                  value={llmState.maxTokens}
                  onChange={(e) => updateLlm({ maxTokens: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg bg-surface-2 border border-surface-3 text-sm text-zinc-200 focus:outline-none focus:border-brand/50"
                />
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-500">
              <span>当前模型：{llmState.displayName}</span>
              {llmProviders.find((item) => item.name === llmState.provider)?.signup_url && (
                <a
                  href={llmProviders.find((item) => item.name === llmState.provider)?.signup_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-brand hover:underline flex items-center gap-1"
                >
                  <ExternalLink className="w-3 h-3" /> 获取 API Key
                </a>
              )}
              {llmState.testStatus !== "idle" && llmState.testStatus !== "testing" && (
                <span className={cn("flex items-center gap-1", llmState.testStatus === "success" ? "text-emerald-400" : "text-red-400")}>
                  {llmState.testStatus === "success" ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
                  {llmState.testMessage}
                  {llmState.testLatency && <span className="text-zinc-500 ml-1">({llmState.testLatency}ms)</span>}
                </span>
              )}
            </div>
          </div>
        )}

        {/* Category filter tabs */}
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setFilterCat("all")}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
              filterCat === "all" ? "bg-brand/15 text-brand" : "bg-surface-2 text-zinc-400 hover:text-zinc-300"
            )}
          >
            全部 ({providers.length})
          </button>
          {CATEGORIES.map((cat) => {
            const count = providers.filter((p) => p.meta.categories.includes(cat.key)).length;
            return (
              <button
                key={cat.key}
                onClick={() => setFilterCat(cat.key)}
                className={cn(
                  "px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                  filterCat === cat.key ? `${CATEGORY_BADGE[cat.key].bg} ${CATEGORY_BADGE[cat.key].text}` : "bg-surface-2 text-zinc-400 hover:text-zinc-300"
                )}
              >
                {cat.label} ({count})
              </button>
            );
          })}
        </div>

        {/* Provider cards */}
        <div className="space-y-3">
          {filtered.map((p, _fi) => {
            const idx = providers.indexOf(p);
            return (
              <ProviderCard
                key={p.meta.name}
                state={p}
                onToggleExpand={() =>
                  setProviders((prev) => {
                    const next = [...prev];
                    next[idx] = { ...next[idx], expanded: !next[idx].expanded };
                    return next;
                  })
                }
                onToggleEnabled={() => update(idx, { enabled: !p.enabled })}
                onApiKeyChange={(v) => update(idx, { apiKeyInput: v })}
                onToggleShowKey={() =>
                  setProviders((prev) => {
                    const next = [...prev];
                    next[idx] = { ...next[idx], showKey: !next[idx].showKey };
                    return next;
                  })
                }
                onPriorityChange={(cat, val) =>
                  update(idx, {
                    priorityOverrides: { ...p.priorityOverrides, [cat]: val },
                  })
                }
                onTest={() => handleTest(idx)}
              />
            );
          })}
        </div>

        {/* Legend */}
        <div className="text-xs text-zinc-500 flex items-center gap-4 pt-4 border-t border-surface-2">
          <span className="flex items-center gap-1"><CheckCircle2 className="w-3 h-3 text-emerald-400" /> 已实现</span>
          <span className="flex items-center gap-1"><Construction className="w-3 h-3 text-amber-400" /> 骨架 (待实现)</span>
          <span>优先级数字越小越优先</span>
        </div>
      </div>
    </div>
  );
}

/* ── Provider Card Component ──────────────────────────────────────── */

function ProviderCard({
  state,
  onToggleExpand,
  onToggleEnabled,
  onApiKeyChange,
  onToggleShowKey,
  onPriorityChange,
  onTest,
}: {
  state: ProviderState;
  onToggleExpand: () => void;
  onToggleEnabled: () => void;
  onApiKeyChange: (v: string) => void;
  onToggleShowKey: () => void;
  onPriorityChange: (cat: string, val: number) => void;
  onTest: () => void;
}) {
  const { meta, config, apiKeyInput, showKey, enabled, priorityOverrides, testStatus, testMessage, testLatency, dirty, expanded } = state;

  const statusIcon = !meta.implemented ? (
    <Construction className="w-4 h-4 text-amber-400" />
  ) : config?.has_key ? (
    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
  ) : meta.requires_key ? (
    <AlertTriangle className="w-4 h-4 text-zinc-500" />
  ) : (
    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
  );

  return (
    <div
      className={cn(
        "rounded-xl border transition-all",
        dirty ? "border-brand/40 bg-brand/5" : "border-surface-2 bg-surface-1",
        !enabled && "opacity-60"
      )}
    >
      {/* Header row */}
      <button
        onClick={onToggleExpand}
        className="w-full flex items-start gap-3 px-4 py-3 text-left"
      >
        {statusIcon}
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-sm">{meta.display_name}</span>
            {!meta.implemented && (
              <span className="px-1.5 py-0.5 rounded text-[10px] bg-amber-500/15 text-amber-400 font-medium">
                SKELETON
              </span>
            )}
            {meta.free_tier && (
              <span className="px-1.5 py-0.5 rounded text-[10px] bg-surface-2 text-zinc-400">
                {meta.free_tier}
              </span>
            )}
            {config?.source && config.source !== "default" && (
              <span className={cn(
                "px-1.5 py-0.5 rounded text-[10px] font-medium",
                config.source === "user" ? "bg-blue-500/15 text-blue-400" :
                config.source === "global" ? "bg-amber-500/15 text-amber-400" :
                "bg-zinc-500/15 text-zinc-400"
              )}>
                {config.source === "user" ? "用户" : config.source === "global" ? "全局" : config.source}
              </span>
            )}
          </div>
          <p className="text-xs text-zinc-500 truncate mt-0.5">{meta.description}</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 shrink-0">
          {/* Category badges */}
          {meta.categories.map((cat) => (
            <span
              key={cat}
              className={cn("px-1.5 py-0.5 rounded text-[10px] font-medium", CATEGORY_BADGE[cat]?.bg, CATEGORY_BADGE[cat]?.text)}
            >
              {CATEGORIES.find((c) => c.key === cat)?.label ?? cat}
            </span>
          ))}
          {expanded ? <ChevronUp className="w-4 h-4 text-zinc-500" /> : <ChevronDown className="w-4 h-4 text-zinc-500" />}
        </div>
      </button>

      {/* Expanded details */}
      {expanded && (
        <div className="px-4 pb-4 pt-1 border-t border-surface-2 space-y-3">
          {/* Enable toggle */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-zinc-400">启用</span>
            <button
              type="button"
              onClick={onToggleEnabled}
              aria-pressed={enabled}
              className={cn(
                "relative h-5 w-10 rounded-full transition-colors",
                enabled ? "bg-brand" : "bg-zinc-600"
              )}
            >
              <span
                className={cn(
                  "absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition-transform",
                  enabled ? "translate-x-5" : "translate-x-0"
                )}
              />
            </button>
          </div>

          {/* API Key input */}
          {meta.requires_key && (
            <div className="space-y-1.5">
              <label className="text-xs text-zinc-400 flex items-center gap-1">
                <Key className="w-3 h-3" />
                API Key
                {config?.has_key && (
                  <span className="text-zinc-500 ml-1">({config.api_key_masked})</span>
                )}
              </label>
              <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                <div className="flex-1 relative">
                  <input
                    type={showKey ? "text" : "password"}
                    value={apiKeyInput}
                    onChange={(e) => onApiKeyChange(e.target.value)}
                    placeholder={config?.has_key ? "留空保持不变" : "输入 API Key"}
                    className="w-full px-3 py-1.5 rounded-lg bg-surface-2 border border-surface-3 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-brand/50"
                  />
                  <button
                    onClick={onToggleShowKey}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                  >
                    {showKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                  </button>
                </div>
                {/* Test button */}
                <button
                  onClick={onTest}
                  disabled={testStatus === "testing" || !meta.implemented}
                  className={cn(
                    "flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-all whitespace-nowrap",
                    testStatus === "testing"
                      ? "bg-surface-2 text-zinc-400"
                      : meta.implemented
                        ? "bg-surface-2 text-zinc-300 hover:bg-surface-3"
                        : "bg-surface-2 text-zinc-600 cursor-not-allowed"
                  )}
                >
                  {testStatus === "testing" ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <Zap className="w-3 h-3" />
                  )}
                  测试
                </button>
              </div>
              {/* Test result */}
              {testStatus !== "idle" && testStatus !== "testing" && (
                <div className={cn(
                  "text-xs flex items-center gap-1 mt-1",
                  testStatus === "success" ? "text-emerald-400" : "text-red-400"
                )}>
                  {testStatus === "success" ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
                  {testMessage}
                  {testLatency && <span className="text-zinc-500 ml-1">({testLatency}ms)</span>}
                </div>
              )}
              {meta.signup_url && (
                <a
                  href={meta.signup_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-brand hover:underline flex items-center gap-1"
                >
                  <ExternalLink className="w-3 h-3" /> 获取 API Key
                </a>
              )}
            </div>
          )}

          {/* No key providers - just a test button */}
          {!meta.requires_key && meta.implemented && (
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={onTest}
                disabled={testStatus === "testing"}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-2 text-zinc-300 hover:bg-surface-3 transition-all"
              >
                {testStatus === "testing" ? <Loader2 className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
                测试连接
              </button>
              {testStatus !== "idle" && testStatus !== "testing" && (
                <span className={cn("text-xs flex items-center gap-1", testStatus === "success" ? "text-emerald-400" : "text-red-400")}>
                  {testStatus === "success" ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
                  {testMessage}
                  {testLatency && <span className="text-zinc-500 ml-1">({testLatency}ms)</span>}
                </span>
              )}
            </div>
          )}

          {/* Priority overrides */}
          <div className="space-y-1.5">
            <label className="text-xs text-zinc-400">分类优先级 (数字越小越优先)</label>
            <div className="flex flex-wrap gap-2">
              {meta.categories.map((cat) => (
                <div key={cat} className="flex items-center gap-1.5">
                  <span className={cn("text-[10px] font-medium", CATEGORY_BADGE[cat]?.text)}>
                    {CATEGORIES.find((c) => c.key === cat)?.label ?? cat}
                  </span>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={priorityOverrides[cat] ?? ""}
                    onChange={(e) => {
                      const val = parseInt(e.target.value);
                      if (!isNaN(val) && val > 0) onPriorityChange(cat, val);
                    }}
                    placeholder="auto"
                    className="w-14 px-2 py-1 rounded bg-surface-2 border border-surface-3 text-xs text-zinc-300 text-center focus:outline-none focus:border-brand/50"
                  />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
