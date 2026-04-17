"use client";



import { useState, useEffect, useCallback, createContext, useContext, useRef } from "react";

import { AlertCircle, Sparkles, Zap } from "lucide-react";

import { getApiToken, llmQuickLogin, listLLMProviders, setApiToken, type LLMProviderInfo } from "@/lib/api";

import { LobsterSvgPaths } from "./logo";



/* ── Auth context ── */

interface AuthContextValue {

  logout: () => void;

  animPhase: "logo" | "beam" | null;

  hasUnlocked: boolean;

  beamKey: number;       // React key — increment to remount/replay beam

  triggerBeam: () => void;

}

const AuthContext = createContext<AuthContextValue>({

  logout: () => {},

  animPhase: null,

  hasUnlocked: false,

  beamKey: 0,

  triggerBeam: () => {},

});

export const useAuth = () => useContext(AuthContext);



const LOGO_FADE_MS = 1000;

const OVERLAY_FADE_MS = 400;

const QUICK_LLM_DRAFT_KEY = "atlas_quick_llm_draft_v1";

type LoginMode = "default" | "custom";



export function TokenGate({ children }: { children: React.ReactNode }) {

  const [unlocked, setUnlocked] = useState<boolean | null>(null);

  const [input, setInput] = useState("");

  const [error, setError] = useState("");

  const [checking, setChecking] = useState(false);

  const [loginMode, setLoginMode] = useState<LoginMode>("default");
  const [llmProviders, setLlmProviders] = useState<LLMProviderInfo[]>([]);
  const [llmProvider, setLlmProvider] = useState("openai_compatible");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmBaseUrl, setLlmBaseUrl] = useState("");
  const [llmToolModel, setLlmToolModel] = useState("");
  const [llmReasoningModel, setLlmReasoningModel] = useState("");
  const [llmToolTemperature, setLlmToolTemperature] = useState("0");
  const [llmReasoningTemperature, setLlmReasoningTemperature] = useState("0.3");
  const [llmMaxTokens, setLlmMaxTokens] = useState("4096");

  const selectedProviderMeta = llmProviders.find((item) => item.name === llmProvider);



  // Animation

  const [showOverlay, setShowOverlay] = useState(false);

  const [animPhase, setAnimPhase] = useState<"logo" | "beam" | null>(null);

  const [hasUnlocked, setHasUnlocked] = useState(false);

  const [beamKey, setBeamKey] = useState(0);

  const hasAutoTriggeredUnlockBeam = useRef(false);

  const triggerBeam = useCallback(() => {

    setHasUnlocked(true);

    setBeamKey((k) => k + 1);

  }, []);



  const verifyToken = useCallback(async (token: string): Promise<boolean> => {

    setApiToken(token);

    try {

      const base = process.env.NEXT_PUBLIC_API_BASE || "/api/v1";

      const headers: Record<string, string> = { "Content-Type": "application/json" };

      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch(`${base}/auth/verify`, { headers });

      return res.ok;

    } catch {

      setApiToken("");

      return false;

    }

  }, []);



  useEffect(() => {
    const existing = getApiToken();

    if (existing) {

      verifyToken(existing).then((ok) => setUnlocked(ok ? true : false));

    } else {

      verifyToken("").then((ok) => setUnlocked(ok ? true : false));

    }

  }, [verifyToken]);

  useEffect(() => {
    let alive = true;

    listLLMProviders()
      .then((res) => {
        if (!alive) return;
        setLlmProviders(res.providers);

        const saved = typeof window !== "undefined" ? window.localStorage.getItem(QUICK_LLM_DRAFT_KEY) : null;
        const parsed = saved ? JSON.parse(saved) as Partial<Record<string, string>> : null;
        const preferred = parsed?.provider && res.providers.some((item) => item.name === parsed.provider)
          ? parsed.provider
          : (res.providers.find((item) => item.name === "openai_compatible")?.name || res.providers[0]?.name || "openai_compatible");
        const meta = res.providers.find((item) => item.name === preferred);
        setLlmProvider(preferred);
        setLlmApiKey(parsed?.apiKey || "");
        setLlmBaseUrl(parsed?.baseUrl || "");
        setLlmToolModel(parsed?.toolModel || meta?.default_tool_model || "");
        setLlmReasoningModel(parsed?.reasoningModel || meta?.default_reasoning_model || "");
        setLlmToolTemperature(parsed?.toolTemperature || "0");
        setLlmReasoningTemperature(parsed?.reasoningTemperature || "0.3");
        setLlmMaxTokens(parsed?.maxTokens || "4096");
      })
      .catch(() => {
        if (!alive) return;
        setLlmProviders([]);
      });

    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(QUICK_LLM_DRAFT_KEY, JSON.stringify({
      provider: llmProvider,
      apiKey: llmApiKey,
      baseUrl: llmBaseUrl,
      toolModel: llmToolModel,
      reasoningModel: llmReasoningModel,
      toolTemperature: llmToolTemperature,
      reasoningTemperature: llmReasoningTemperature,
      maxTokens: llmMaxTokens,
    }));
  }, [llmProvider, llmApiKey, llmBaseUrl, llmToolModel, llmReasoningModel, llmToolTemperature, llmReasoningTemperature, llmMaxTokens]);

  useEffect(() => {
    if (!unlocked) return;
    if (hasAutoTriggeredUnlockBeam.current) return;
    hasAutoTriggeredUnlockBeam.current = true;
    triggerBeam();
  }, [unlocked, triggerBeam]);



  const handleSubmit = async () => {

    const token = input.trim();

    if (!token) {

      setError("请输入访问密钥");

      return;

    }

    setChecking(true);

    setError("");

    const ok = await verifyToken(token);

    setChecking(false);

    if (ok) {

      // Token is already saved by verifyToken → reload to start a completely fresh session
      window.location.reload();

    } else {

      setError("密钥无效或后端不可达");

    }

  };

  const handleLlmLogin = async () => {
    const selected = llmProviders.find((item) => item.name === llmProvider);
    if (!llmApiKey.trim()) {
      setError("请输入你自己的大模型 API Key");
      return;
    }
    setChecking(true);
    setError("");
    try {
      const res = await llmQuickLogin({
        provider: llmProvider,
        api_key: llmApiKey.trim(),
        base_url: selected?.supports_custom_base_url ? (llmBaseUrl.trim() || null) : null,
        tool_calling_model: llmToolModel.trim() || selected?.default_tool_model || null,
        reasoning_model: llmReasoningModel.trim() || selected?.default_reasoning_model || null,
        tool_calling_temperature: Number(llmToolTemperature || 0),
        reasoning_temperature: Number(llmReasoningTemperature || 0.3),
        max_tokens: Number(llmMaxTokens || 4096),
      });
      if (res.success === false) {
        setError(res.message || "模型连通性校验失败");
        setChecking(false);
        return;
      }
      setApiToken(res.token || "");
      window.location.reload();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "大模型登录失败");
      setChecking(false);
    }
  };



  const logout = useCallback(async () => {

    try {

      const base = process.env.NEXT_PUBLIC_API_BASE || "/api/v1";

      const token = getApiToken();

      const headers: Record<string, string> = { "Content-Type": "application/json" };

      if (token) headers["Authorization"] = `Bearer ${token}`;

      await fetch(`${base}/auth/logout`, { method: "POST", headers });

    } catch { /* best-effort */ }

    setApiToken("");

    // Hard reload to clear all in-memory state (analysis cache, chat, watchlist, etc.)
    window.location.reload();

  }, []);



  // Checking on mount

  if (unlocked === null) {

    return (

      <div className="h-screen flex items-center justify-center bg-[var(--surface-0)]">

        <div className="animate-pulse text-sm text-zinc-500">验证中...</div>

      </div>

    );

  }



  // Unlocked — render children + optional overlay

  if (unlocked) {

    return (

      <AuthContext.Provider value={{ logout, animPhase, hasUnlocked, beamKey, triggerBeam }}>

        {children}

        {showOverlay && (

          <div

            className="fixed inset-0 z-[9998] bg-[var(--surface-0)] pointer-events-none"

            style={{ animation: `fadeOut ${OVERLAY_FADE_MS}ms ease-out forwards` }}

          />

        )}

      </AuthContext.Provider>

    );

  }



  // Locked

  return (

    <div className="h-screen flex items-center justify-center bg-[var(--surface-0)]">

      <div className="w-full max-w-sm mx-4">

        <div className="text-center mb-8">

          <svg

            width="56"

            height="56"

            viewBox="0 0 32 32"

            fill="none"

            xmlns="http://www.w3.org/2000/svg"

            className="mx-auto mb-4"

          >

            <LobsterSvgPaths />

          </svg>

          <h1 className="text-xl font-bold text-zinc-100 mb-1">StockClaw 智能投研平台</h1>

          <p className="text-sm text-zinc-500">默认模型需要输入管理员 token，自带模型可直接填写 API 进入</p>

        </div>



        <div className="space-y-3">

          <div className="grid grid-cols-2 gap-2 rounded-xl bg-zinc-900/70 p-1 border border-zinc-800">
            {[
              { key: "default", label: "默认进入", icon: Sparkles },
              { key: "custom", label: "自带模型", icon: Zap },
            ].map((item) => (
              <button
                key={item.key}
                onClick={() => { setLoginMode(item.key as LoginMode); setError(""); }}
                className={`w-full flex items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-medium transition-colors ${loginMode === item.key ? "bg-emerald-600 text-white" : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"}`}
              >
                <item.icon className="w-3.5 h-3.5" />
                {item.label}
              </button>
            ))}
          </div>

          {loginMode === "default" && (
            <div className="space-y-3 rounded-2xl border border-zinc-800 bg-zinc-900/60 p-4">
              <p className="text-sm text-zinc-400 leading-6">
                输入你的管理员 token，验证通过后将使用系统默认的大模型配置进入。
              </p>
              <input
                type="password"
                value={input}
                onChange={(e) => { setInput(e.target.value); setError(""); }}
                onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
                placeholder="请输入管理员 token"
                autoFocus
                className="w-full px-4 py-3 rounded-xl bg-zinc-900 border border-zinc-800 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/20 transition-colors"
              />
              <button
                onClick={handleSubmit}
                disabled={checking || !input.trim()}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:bg-zinc-800 disabled:text-zinc-600 text-sm font-medium text-white transition-colors"
              >
                {checking ? <span className="animate-pulse">验证中...</span> : <><Sparkles className="w-4 h-4" /> 使用默认模型进入</>}
              </button>
            </div>
          )}

          {loginMode === "custom" && (
            <div className="space-y-3 rounded-2xl border border-zinc-800 bg-zinc-900/60 p-4">
              <p className="text-sm text-zinc-400 leading-6">
                请输入后端支持的 `provider` 形式和你自己的 API Token，其他参数使用默认推荐值。
              </p>
              <div>
                <label className="text-xs text-zinc-500 mb-1.5 block">Provider</label>
                <input
                  type="text"
                  list="atlas-llm-provider-options"
                  value={llmProvider}
                  onChange={(e) => {
                    const next = e.target.value;
                    const meta = llmProviders.find((item) => item.name === next);
                    setLlmProvider(next);
                    if (meta) {
                      setLlmToolModel(meta.default_tool_model || "");
                      setLlmReasoningModel(meta.default_reasoning_model || "");
                    }
                    setError("");
                  }}
                  placeholder="例如 openai_compatible / deepseek / minimax / zhipu"
                  className="w-full px-4 py-3 rounded-xl bg-zinc-900 border border-zinc-800 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/20 transition-colors"
                />
                <datalist id="atlas-llm-provider-options">
                  {llmProviders.map((item) => (
                    <option key={item.name} value={item.name} />
                  ))}
                </datalist>
                <p className="mt-1.5 text-[11px] text-zinc-600">
                  请输入正确的 provider 形式，如 `openai_compatible`、`deepseek`、`minimax`、`zhipu`
                </p>
              </div>

              <div>
                <label className="text-xs text-zinc-500 mb-1.5 block">API Token / API Key</label>
                <input
                  type="password"
                  value={llmApiKey}
                  onChange={(e) => { setLlmApiKey(e.target.value); setError(""); }}
                  placeholder={selectedProviderMeta ? `请输入 ${selectedProviderMeta.display_name} 的 API Token / API Key` : "请输入对应 provider 的 API Token / API Key"}
                  className="w-full px-4 py-3 rounded-xl bg-zinc-900 border border-zinc-800 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/20 transition-colors"
                />
              </div>

              <button
                onClick={handleLlmLogin}
                disabled={checking || !llmApiKey.trim() || !llmProvider.trim()}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:bg-zinc-800 disabled:text-zinc-600 text-sm font-medium text-white transition-colors"
              >
                {checking ? <span className="animate-pulse">验证中...</span> : <><Zap className="w-4 h-4" /> 使用我的模型进入</>}
              </button>
            </div>
          )}

          {error && (

            <div className="flex items-center gap-1.5 text-xs text-red-400 px-1">

              <AlertCircle className="w-3.5 h-3.5 shrink-0" />

              {error}

            </div>

          )}



          

        </div>



        <p className="text-center text-[11px] text-zinc-600 mt-6">

          默认模式需管理员 token · 自带模型模式会为你生成独立会话

        </p>

        <p className="text-center text-[11px] text-zinc-600 mt-2">

          联系作者：<a href="mailto:doriany7702@gmail.com" className="text-emerald-500/70 hover:text-emerald-400 transition-colors">doriany7702@gmail.com</a>

        </p>

      </div>

    </div>

  );

}

