/* --------------------------------------------------------
   Atlas Backend API client
   -------------------------------------------------------- */

const BASE = process.env.NEXT_PUBLIC_API_BASE || "/api/v1";
// Long-running endpoints bypass Next.js proxy (which times out at ~60s).
// CORS is enabled on the backend for localhost:3000.
// In production (behind nginx), DIRECT_BASE can be same-origin "/api/v1".
// In local dev, it defaults to localhost:8000 to bypass Next.js proxy timeout.
const DIRECT_BASE = process.env.NEXT_PUBLIC_API_DIRECT
  || (typeof window !== "undefined" && window.location.hostname !== "localhost"
    ? "/api/v1"
    : `${process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000"}/api/v1`);

/* ── API Token management ── */
const TOKEN_KEY = "atlas_api_token";

export function getApiToken(): string {
  if (typeof window === "undefined") return "";
  const persistent = window.localStorage.getItem(TOKEN_KEY);
  if (persistent) return persistent;
  const legacy = window.sessionStorage.getItem(TOKEN_KEY) || "";
  if (legacy) {
    window.localStorage.setItem(TOKEN_KEY, legacy);
    window.sessionStorage.removeItem(TOKEN_KEY);
  }
  return legacy;
}

export function setApiToken(token: string) {
  if (typeof window === "undefined") return;
  if (token) {
    const normalized = token.trim();
    window.localStorage.setItem(TOKEN_KEY, normalized);
    window.sessionStorage.removeItem(TOKEN_KEY);
  } else {
    window.localStorage.removeItem(TOKEN_KEY);
    window.sessionStorage.removeItem(TOKEN_KEY);
  }
}

function authHeaders(): Record<string, string> {
  const token = getApiToken();
  if (!token) return {};
  return { Authorization: `Bearer ${token}` };
}

export interface AuthIdentity {
  status: string;
  user_id: string;
  is_admin: boolean;
}

export async function getAuthIdentity(): Promise<AuthIdentity> {
  const token = getApiToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${BASE}/auth/verify`, { headers });
  if (!res.ok) {
    if (res.status === 401) setApiToken("");
    throw new Error("Failed to resolve current auth identity");
  }
  return res.json() as Promise<AuthIdentity>;
}

/** Resolve the current persisted user_id from the backend auth layer. */
export async function getUserId(): Promise<string> {
  try {
    const identity = await getAuthIdentity();
    return identity.user_id || "default-user";
  } catch {
    return "default-user";
  }
}

async function request<T>(path: string, options?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const { timeoutMs, ...fetchOpts } = options ?? {};
  const controller = timeoutMs ? new AbortController() : undefined;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : undefined;
  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json", ...authHeaders(), ...(fetchOpts?.headers as Record<string, string>) },
      ...fetchOpts,
      ...(controller ? { signal: controller.signal } : {}),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      if (res.status === 401) {
        setApiToken("");
        if (typeof window !== "undefined") window.location.reload();
      }
      throw new Error(body.detail || body.error || res.statusText);
    }
    return res.json();
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/* Chat (non-streaming) */
export async function chat(message: string, sessionId?: string) {
  return request<{ session_id: string; message: string }>("/chat", {
    method: "POST",
    body: JSON.stringify({ message, session_id: sessionId, stream: false }),
  });
}

/* Chat SSE streaming */
export interface StreamCallbacks {
  onToken?: (token: string) => void;
  onToolStart?: (tool: string) => void;
  onToolEnd?: (tool: string) => void;
  onStepStart?: (node: string, tools: string[]) => void;
  onStepEnd?: (node: string) => void;
  onDone?: (sessionId: string) => void;
  onConfigUpdate?: (params: Record<string, unknown>) => void;
  onWatchlistUpdate?: (tickers: string[], action?: string) => void;
  onTickerSelect?: (ticker: string, name?: string) => void;
  onMultiAnalyze?: (tickers: string[]) => void;
  onDisambiguate?: (tickers: string[], sessionId: string) => void;
  onHarnessEvent?: (event: { module: string; [key: string]: unknown }) => void;
  onResolveFail?: (query: string, message: string) => void;
  onIntentDone?: (intent: string, content: string, index: number, total: number) => void;
}

export async function chatStream(
  message: string,
  sessionId?: string,
  callbacks?: StreamCallbacks
) {
  const res = await fetch(`${DIRECT_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ message, session_id: sessionId, stream: true }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    if (res.status === 401) {
      setApiToken("");
      if (typeof window !== "undefined") window.location.reload();
    }
    throw new Error(body.detail || body.error || res.statusText);
  }
  const sid = res.headers.get("X-Session-Id") || sessionId || "";
  const reader = res.body?.getReader();
  if (!reader) return sid;
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6).trim();
        if (data === "[DONE]") {
          callbacks?.onDone?.(sid);
          return sid;
        }
        try {
          const parsed = JSON.parse(data);
          if (parsed.type === "token" && parsed.content) {
            callbacks?.onToken?.(parsed.content);
          } else if (parsed.type === "tool_start") {
            callbacks?.onToolStart?.(parsed.tool);
          } else if (parsed.type === "tool_end") {
            callbacks?.onToolEnd?.(parsed.tool);
          } else if (parsed.type === "step_start") {
            callbacks?.onStepStart?.(parsed.node, parsed.tools || []);
          } else if (parsed.type === "step_end") {
            callbacks?.onStepEnd?.(parsed.node);
          } else if (parsed.type === "config_update") {
            callbacks?.onConfigUpdate?.(parsed.params || {});
          } else if (parsed.type === "watchlist_update") {
            callbacks?.onWatchlistUpdate?.(parsed.tickers || [], parsed.action || "add");
          } else if (parsed.type === "ticker_select") {
            callbacks?.onTickerSelect?.(parsed.ticker, parsed.name);
          } else if (parsed.type === "resolve_fail") {
            callbacks?.onResolveFail?.(parsed.query || "", parsed.message || "");
          } else if (parsed.type === "multi_analyze") {
            callbacks?.onMultiAnalyze?.(parsed.tickers || []);
          } else if (parsed.type === "disambiguate") {
            callbacks?.onDisambiguate?.(parsed.tickers || [], parsed.session_id || "");
          } else if (parsed.type === "harness_event") {
            callbacks?.onHarnessEvent?.(parsed as { module: string; [key: string]: unknown });
          } else if (parsed.type === "intent_done") {
            callbacks?.onIntentDone?.(parsed.intent || "", parsed.content || "", parsed.index ?? 0, parsed.total ?? 1);
          }
        } catch {}
      }
    }
  }
  callbacks?.onDone?.(sid);
  return sid;
}

/* Explain — lightweight LLM streaming, no graph routing */
export async function explainStream(
  prompt: string,
  onToken: (token: string) => void,
): Promise<void> {
  const res = await fetch(`${DIRECT_BASE}/explain`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ prompt }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    if (res.status === 401) { setApiToken(""); if (typeof window !== "undefined") window.location.reload(); }
    throw new Error(body.detail || body.error || res.statusText);
  }
  const reader = res.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6).trim();
        if (data === "[DONE]") return;
        try {
          const parsed = JSON.parse(data);
          if (parsed.type === "token" && parsed.content) {
            onToken(parsed.content);
          }
        } catch {}
      }
    }
  }
}

/* Strong stocks */
export async function fetchStrongStocks(params?: {
  market_type?: string;
  top_count?: number;
  rsi_threshold?: number;
  sort_by?: string;
  min_volume_turnover?: number;
}) {
  return request<{ market_type: string; stocks: Record<string, unknown>[]; filters_applied: Record<string, unknown> }>("/strong-stocks", {
    method: "POST",
    body: JSON.stringify({ market_type: "us_stock", ...params }),
  });
}

export async function fetchSingleStrongStock(params: {
  ticker: string;
  market_type?: "us_stock" | "hk_stock" | "etf";
}) {
  return request<{ market_type: string; stock: Record<string, unknown>; timestamp: string }>("/strong-stocks/single", {
    method: "POST",
    body: JSON.stringify({ market_type: "us_stock", ...params }),
  });
}

/* Analyze — long-running: graph may take 2-4 min.
   Calls backend directly (CORS) to avoid Next.js proxy 60s timeout. */
export async function analyze(ticker: string, sessionId?: string, deepDocumentText?: string) {
  const { timeoutMs, ...fetchOpts } = {
    method: "POST" as const,
    body: JSON.stringify({ ticker, session_id: sessionId, deep_document_text: deepDocumentText }),
    timeoutMs: 5 * 60 * 1000,
  };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${DIRECT_BASE}/analyze`, {
      headers: { "Content-Type": "application/json", ...authHeaders() },
      ...fetchOpts,
      signal: controller.signal,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      if (res.status === 401) { setApiToken(""); if (typeof window !== "undefined") window.location.reload(); }
      throw new Error(body.detail || body.error || res.statusText);
    }
    return res.json() as Promise<{
      ticker: string;
      report: string;
      structured: Record<string, unknown> | null;
      errors: string[];
      evidence_chain: Record<string, unknown>[];
      retrieval_debug: Record<string, unknown>;
    }>;
  } finally {
    clearTimeout(timer);
  }
}

/* Analyze SSE streaming — shows tool call progress in real-time */
export interface AnalyzeStreamCallbacks {
  onToolStart?: (tool: string) => void;
  onToolEnd?: (tool: string) => void;
  onStepStart?: (node: string, tools: string[]) => void;
  onStepEnd?: (node: string) => void;
  onToken?: (token: string) => void;
  onHarnessEvent?: (event: { module: string; [key: string]: unknown }) => void;
}

export async function analyzeStream(
  ticker: string,
  sessionId?: string,
  callbacks?: AnalyzeStreamCallbacks,
  deepDocumentText?: string,
): Promise<{
  ticker: string;
  report: string;
  structured: Record<string, unknown> | null;
  errors: string[];
  evidence_chain: Record<string, unknown>[];
  retrieval_debug: Record<string, unknown>;
}> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5 * 60 * 1000);
  try {
    const res = await fetch(`${DIRECT_BASE}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ ticker, session_id: sessionId, stream: true, deep_document_text: deepDocumentText }),
      signal: controller.signal,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      if (res.status === 401) { setApiToken(""); if (typeof window !== "undefined") window.location.reload(); }
      throw new Error(body.detail || body.error || res.statusText);
    }
    const reader = res.body?.getReader();
    if (!reader) throw new Error("No stream body");

    const decoder = new TextDecoder();
    let buffer = "";
    let streamResult: {
      ticker: string;
      report: string;
      structured: Record<string, unknown> | null;
      errors: string[];
      evidence_chain: Record<string, unknown>[];
      retrieval_debug: Record<string, unknown>;
    } | null = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const data = line.slice(6).trim();
        if (data === "[DONE]") break;
        try {
          const p = JSON.parse(data);
          if (p.type === "tool_start") callbacks?.onToolStart?.(p.tool);
          else if (p.type === "tool_end") callbacks?.onToolEnd?.(p.tool);
          else if (p.type === "step_start") callbacks?.onStepStart?.(p.node, p.tools || []);
          else if (p.type === "step_end") callbacks?.onStepEnd?.(p.node);
          else if (p.type === "token" && p.content) callbacks?.onToken?.(p.content);
          else if (p.type === "result") {
            streamResult = {
              ticker: p.ticker || ticker,
              report: p.report || "",
              structured: p.structured || null,
              errors: p.errors || [],
              evidence_chain: p.evidence_chain || [],
              retrieval_debug: p.retrieval_debug || {},
            };
          } else if (p.type === "harness_event") {
            callbacks?.onHarnessEvent?.(p as { module: string; [key: string]: unknown });
          }
        } catch {}
      }
    }

    if (streamResult) return streamResult;
    // Fallback: if stream didn't include result event, fetch non-streaming
    return analyze(ticker, sessionId, deepDocumentText);
  } finally {
    clearTimeout(timer);
  }
}

/* Resume chat after disambiguation (Human-in-the-loop) */
export async function resumeChat(
  sessionId: string,
  selectedTicker: string,
  callbacks?: StreamCallbacks,
) {
  const res = await fetch(`${DIRECT_BASE}/chat/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ session_id: sessionId, selected_ticker: selectedTicker, stream: true }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    if (res.status === 401) { setApiToken(""); if (typeof window !== "undefined") window.location.reload(); }
    throw new Error(body.detail || body.error || res.statusText);
  }
  const reader = res.body?.getReader();
  if (!reader) return sessionId;
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6).trim();
        if (data === "[DONE]") {
          callbacks?.onDone?.(sessionId);
          return sessionId;
        }
        try {
          const parsed = JSON.parse(data);
          if (parsed.type === "token" && parsed.content) callbacks?.onToken?.(parsed.content);
          else if (parsed.type === "tool_start") callbacks?.onToolStart?.(parsed.tool);
          else if (parsed.type === "tool_end") callbacks?.onToolEnd?.(parsed.tool);
          else if (parsed.type === "step_start") callbacks?.onStepStart?.(parsed.node, parsed.tools || []);
          else if (parsed.type === "step_end") callbacks?.onStepEnd?.(parsed.node);
          else if (parsed.type === "ticker_select") callbacks?.onTickerSelect?.(parsed.ticker, parsed.name);
          else if (parsed.type === "harness_event") callbacks?.onHarnessEvent?.(parsed as { module: string; [key: string]: unknown });
        } catch {}
      }
    }
  }
  callbacks?.onDone?.(sessionId);
  return sessionId;
}

/* Watchlist */
export async function getWatchlist(userId: string) {
  return request<{ user_id: string; watchlist: { ticker: string; note: string; added_at: string }[]; count: number }>(
    `/watchlist/${userId}`
  );
}

export async function addToWatchlist(userId: string, ticker: string, note = "") {
  return request<{ user_id: string; watchlist: { ticker: string; note: string; added_at: string }[]; count: number }>("/watchlist", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, ticker, note }),
  });
}

export async function removeFromWatchlist(userId: string, ticker: string) {
  return request<{ ok: boolean }>(`/watchlist/${userId}/${ticker}`, { method: "DELETE" });
}

export async function updateWatchlistNote(userId: string, ticker: string, note: string) {
  return request<{ user_id: string; watchlist: { ticker: string; note: string; added_at: string }[] }>("/watchlist", {
    method: "PUT",
    body: JSON.stringify({ user_id: userId, ticker, note }),
  });
}

/* Watchlist upcoming events */
export interface WatchlistEvent {
  ticker: string;
  event: string;
  date: string;
  days_away: number;
  detail?: string;
  category?: "earnings" | "dividend" | "policy";
}

export async function fetchWatchlistEvents(tickers: string[]) {
  return request<{ events: WatchlistEvent[] }>("/watchlist-events", {
    method: "POST",
    body: JSON.stringify({ tickers }),
    timeoutMs: 30_000,
  });
}

/* Long-term Memory */
export interface MemoryItem {
  key: string;
  content: string;
  updated_at: number;
  access_count: number;
}

export async function getMemories(userId: string) {
  return request<{ user_id: string; memories: Record<string, MemoryItem[]>; total: number }>(
    `/memory/${userId}`
  );
}

export async function getMemoriesByCategory(userId: string, category: string) {
  return request<{ user_id: string; category: string; memories: MemoryItem[]; total: number }>(
    `/memory/${userId}/${category}`
  );
}

export async function deleteMemory(userId: string, category: string, key: string) {
  return request<{ ok: boolean }>(`/memory/${userId}/${category}/${encodeURIComponent(key)}`, {
    method: "DELETE",
  });
}

export async function clearAllMemories(userId: string) {
  return request<{ ok: boolean; removed_count: number }>(`/memory/${userId}`, {
    method: "DELETE",
  });
}

/* ── Agent Tasks (autonomous harness) ── */

export interface TaskSpec {
  task_id: string;
  user_id: string;
  goal: string;
  ticker_scope: string[];
  kpi_constraints: Record<string, unknown>;
  cadence: string;
  report_template: string;
  stop_conditions: Record<string, unknown>;
  escalation_policy: string;
  status: string;
  created_at: number;
  updated_at: number;
}

export interface CycleResult {
  cycle_id: string;
  task_id: string;
  status: string;
  quality_score?: number;
  tickers_analyzed?: string[];
  started_at: number;
  finished_at?: number;
  error?: string;
  [key: string]: unknown;
}

export interface ResidentAgentCycleSummary {
  cycle_id: string;
  task_id: string;
  status: string;
  quality_score?: number;
  started_at: number;
  completed_at?: number;
  report_markdown?: string;
  errors?: string[];
  product_summary?: {
    mode?: string;
    watchlist?: {
      overall_stance?: string;
      headline?: string;
      confidence?: string;
      confidence_score?: number;
      symbols_requiring_attention?: string[];
      stable_symbols?: string[];
      major_change_count?: number;
      markdown?: string;
    };
    symbols?: Array<{
      ticker: string;
      stance?: string;
      change_severity?: string;
      update_mode?: string;
      conclusion?: {
        title?: string;
        summary?: string;
        why?: string;
        changes?: string[];
        top_risk?: string;
        top_catalyst?: string;
        confidence?: string;
        confidence_score?: number;
      };
      errors?: string[];
    }>;
  };
}

export interface ResidentAgentStatus {
  user_id: string;
  task_id: string;
  enabled: boolean;
  interval_seconds: number;
  status: string;
  running: boolean;
  last_run_at: number;
  last_error: string;
  updated_at: number;
  watchlist: { ticker: string; note: string; added_at: string }[];
  watchlist_count: number;
  recent_cycles: ResidentAgentCycleSummary[];
  latest_cycle?: ResidentAgentCycleSummary | null;
}

export async function createTask(params: {
  user_id: string;
  goal: string;
  ticker_scope: string[];
  cadence?: string;
  report_template?: string;
  kpi_constraints?: Record<string, unknown>;
  stop_conditions?: Record<string, unknown>;
  escalation_policy?: string;
}) {
  return request<TaskSpec>("/tasks", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function listTasks(userId: string, status?: string) {
  const qs = status ? `?status=${status}` : "";
  return request<{ user_id: string; tasks: TaskSpec[]; count: number }>(
    `/tasks/${userId}${qs}`
  );
}

export async function getTask(userId: string, taskId: string) {
  return request<TaskSpec>(`/tasks/${userId}/${taskId}`);
}

export async function updateTask(
  userId: string,
  taskId: string,
  fields: Partial<Pick<TaskSpec, "goal" | "ticker_scope" | "cadence" | "report_template" | "status" | "escalation_policy">>
) {
  return request<TaskSpec>(`/tasks/${userId}/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify(fields),
  });
}

export async function deleteTask(userId: string, taskId: string) {
  return request<{ ok: boolean }>(`/tasks/${userId}/${taskId}`, {
    method: "DELETE",
  });
}

export interface CycleStreamCallbacks {
  onStep?: (node: string, label: string) => void;
  onTool?: (tool: string) => void;
  onDone?: (result: Record<string, unknown>) => void;
  onError?: (message: string) => void;
}

export async function runTaskCycle(
  userId: string,
  taskId: string,
  callbacks?: CycleStreamCallbacks,
) {
  const res = await fetch(`${DIRECT_BASE}/tasks/${userId}/${taskId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || body.error || res.statusText);
  }
  const reader = res.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = "";
  let result: Record<string, unknown> = {};
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6).trim();
        if (data === "[DONE]") {
          callbacks?.onDone?.(result);
          return result;
        }
        try {
          const parsed = JSON.parse(data);
          if (parsed.type === "step") {
            callbacks?.onStep?.(parsed.node, parsed.label);
          } else if (parsed.type === "tool") {
            callbacks?.onTool?.(parsed.tool);
          } else if (parsed.type === "done") {
            result = parsed;
          } else if (parsed.type === "error") {
            callbacks?.onError?.(parsed.message);
          }
        } catch {}
      }
    }
  }
  return result;
}

export async function listTaskCycles(userId: string, taskId: string, limit = 10) {
  return request<{ task_id: string; cycles: CycleResult[]; count: number }>(
    `/tasks/${userId}/${taskId}/cycles?limit=${limit}`
  );
}

export async function getTaskDashboard(taskId: string) {
  return request<Record<string, unknown>>(`/harness/task-dashboard/${taskId}`);
}

export async function getHarnessDashboard() {
  return request<Record<string, unknown>>("/harness/dashboard");
}

export async function getResidentAgentStatus(userId: string) {
  return request<ResidentAgentStatus>(`/resident-agent/${userId}`);
}

export async function updateResidentAgentStatus(
  userId: string,
  params: { enabled?: boolean; interval_seconds?: number; run_immediately?: boolean },
) {
  return request<ResidentAgentStatus>(`/resident-agent/${userId}`, {
    method: "PUT",
    body: JSON.stringify(params),
  });
}

export async function runResidentAgentOnce(userId: string) {
  return request<ResidentAgentStatus>(`/resident-agent/${userId}/run`, {
    method: "POST",
  });
}

/* ── Data Source Configuration ── */

export interface DataSourceProviderInfo {
  name: string;
  display_name: string;
  description: string;
  categories: string[];
  requires_key: boolean;
  signup_url: string;
  free_tier: string;
  implemented: boolean;
}

export interface DataSourceConfigItem {
  provider_name: string;
  display_name: string;
  has_key: boolean;
  api_key_masked: string;
  enabled: boolean;
  priority_overrides: Record<string, number>;
  source: string;
  implemented: boolean;
}

export interface LLMProviderInfo {
  name: string;
  display_name: string;
  description: string;
  default_tool_model: string;
  default_reasoning_model: string;
  signup_url: string;
  supports_custom_base_url: boolean;
}

export interface LLMConfigResponse {
  provider: string;
  display_name: string;
  has_key: boolean;
  api_key_masked: string;
  base_url?: string | null;
  tool_calling_model: string;
  reasoning_model: string;
  tool_calling_temperature: number;
  reasoning_temperature: number;
  max_tokens: number;
  enabled: boolean;
  source: string;
  supports_custom_base_url: boolean;
}

export interface LLMConfigPayload {
  provider: string;
  api_key?: string | null;
  base_url?: string | null;
  tool_calling_model?: string | null;
  reasoning_model?: string | null;
  tool_calling_temperature?: number;
  reasoning_temperature?: number;
  max_tokens?: number;
  enabled?: boolean;
}

export interface LLMTestPayload {
  provider: string;
  api_key: string;
  base_url?: string | null;
  tool_calling_model?: string | null;
  reasoning_model?: string | null;
  tool_calling_temperature?: number;
  reasoning_temperature?: number;
  max_tokens?: number;
}

export async function llmQuickLogin(payload: LLMTestPayload) {
  return request<{ status?: string; token?: string; user_id?: string; provider?: string; success?: boolean; message?: string; latency_ms?: number }>("/auth/llm-login", {
    method: "POST",
    body: JSON.stringify(payload),
    timeoutMs: 30000,
  });
}

export async function listDataSources() {
  // Public endpoint, no auth needed but we still send it
  return request<{ providers: DataSourceProviderInfo[]; count: number }>("/datasources");
}

export async function listLLMProviders() {
  return request<{ providers: LLMProviderInfo[]; count: number }>("/llm/providers");
}

export async function getLLMConfig(userId: string) {
  return request<{ user_id: string; config: LLMConfigResponse }>(`/llm/config/${userId}`);
}

export async function updateLLMConfig(userId: string, config: LLMConfigPayload) {
  return request<{ user_id: string; config: LLMConfigResponse }>(`/llm/config/${userId}`, {
    method: "PUT",
    body: JSON.stringify(config),
  });
}

export async function deleteLLMConfig(userId: string) {
  return request<{ deleted: boolean; user_id: string }>(`/llm/config/${userId}`, {
    method: "DELETE",
  });
}

export async function testLLMConfig(payload: LLMTestPayload) {
  return request<{ provider: string; success: boolean; message: string; latency_ms?: number }>("/llm/test", {
    method: "POST",
    body: JSON.stringify(payload),
    timeoutMs: 30000,
  });
}

export async function getDataSourceConfig(userId: string) {
  return request<{ user_id: string; configs: DataSourceConfigItem[]; count: number }>(
    `/datasources/config/${userId}`
  );
}

export async function updateDataSourceConfig(
  userId: string,
  configs: { provider_name: string; api_key?: string | null; enabled?: boolean; priority_overrides?: Record<string, number> }[]
) {
  return request<{ user_id: string; updated: unknown[]; count: number }>(
    `/datasources/config/${userId}`,
    { method: "PUT", body: JSON.stringify({ configs }) }
  );
}

export async function deleteDataSourceConfig(userId: string, provider: string) {
  return request<{ deleted: boolean }>(`/datasources/config/${userId}/${provider}`, { method: "DELETE" });
}

export async function testDataSource(provider: string, apiKey: string = "") {
  return request<{ provider: string; success: boolean; message: string; latency_ms?: number }>(
    `/datasources/test/${provider}`,
    { method: "POST", body: JSON.stringify({ api_key: apiKey }), timeoutMs: 30000 }
  );
}

export async function getDataSourcePriority(userId: string, category: string) {
  return request<{ user_id: string; category: string; providers: string[] }>(
    `/datasources/priority/${userId}?category=${category}`
  );
}

/* Health */
export async function health() {
  return request<{ status: string; version: string; llm_provider: string }>("/health");
}
