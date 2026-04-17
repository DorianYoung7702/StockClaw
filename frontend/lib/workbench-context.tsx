"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  useEffect,
  type ReactNode,
} from "react";
import type {
  ChatMessage,
  ScreeningConfig,
  StrongStock,
  StockAnalysis,
  SortField,
} from "@/lib/types";
import { getApiToken, type TaskSpec, type CycleResult } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  sessionId?: string;
  config: ScreeningConfig;
  updatedAt: number;
}

interface WorkbenchState {
  // Chat
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  sessionId: string | undefined;
  setSessionId: (id: string | undefined) => void;
  showWelcome: boolean;
  setShowWelcome: (v: boolean) => void;

  // Config
  config: ScreeningConfig;
  setConfig: React.Dispatch<React.SetStateAction<ScreeningConfig>>;

  // Candidates (strong stocks list)
  candidates: StrongStock[];
  setCandidates: (stocks: StrongStock[]) => void;
  candidatesByMarket: Record<string, StrongStock[]>;
  setCandidatesForMarket: (market: string, stocks: StrongStock[]) => void;
  candidatesLoading: boolean;
  setCandidatesLoading: (v: boolean) => void;
  conditionSummary: string;
  setConditionSummary: (s: string) => void;
  candidatesStale: boolean;
  markCandidatesStale: () => void;

  // Analysis
  selectedTicker: string | null;
  setSelectedTicker: (t: string | null) => void;
  analysisCache: Record<string, StockAnalysis>;
  setAnalysisForTicker: (ticker: string, a: StockAnalysis) => void;
  clearAnalysisForTicker: (ticker: string) => void;
  analysisLoadingTickers: Set<string>;
  setTickerAnalysisLoading: (ticker: string, loading: boolean) => void;

  // Cache helpers
  lastFetchKey: string;
  setLastFetchKey: (k: string) => void;

  // Watchlist
  watchedTickers: Set<string>;
  setWatchedTickers: React.Dispatch<React.SetStateAction<Set<string>>>;

  // Multi-ticker analysis queue (from chat → watchlist page)
  pendingAnalysisTickers: string[];
  setPendingAnalysisTickers: React.Dispatch<React.SetStateAction<string[]>>;

  // Chat history
  chatHistory: ChatSession[];
  saveAndNewSession: () => void;
  switchToSession: (id: string) => void;
  deleteSession: (id: string) => void;

  // Cross-page unread notification
  hasUnreadChat: boolean;
  setHasUnreadChat: (v: boolean) => void;
  /** Push a system message into chat. If `markUnread` is true, sets hasUnreadChat. */
  pushAgentMessage: (content: string, markUnread?: boolean) => void;

  // Agent tasks (persisted across page switches)
  agentTasks: TaskSpec[];
  setAgentTasks: React.Dispatch<React.SetStateAction<TaskSpec[]>>;
  agentTasksLoaded: boolean;
  setAgentTasksLoaded: (v: boolean) => void;
  agentSelectedId: string | null;
  setAgentSelectedId: (id: string | null) => void;
  agentCycles: CycleResult[];
  setAgentCycles: React.Dispatch<React.SetStateAction<CycleResult[]>>;
  agentRunningTasks: Set<string>;
  setAgentRunningTasks: React.Dispatch<React.SetStateAction<Set<string>>>;
  agentDashboard: Record<string, unknown> | null;
  setAgentDashboard: (d: Record<string, unknown> | null) => void;
}

const DEFAULT_CONFIG: ScreeningConfig = {
  market_type: "us_stock",
  top_count: 10,
  rsi_threshold: 48,
  momentum_days: [15, 30, 60, 120],
  top_volume_count: 500,
  sort_by: "momentum_score" as SortField,
};

// ---------------------------------------------------------------------------
// Session storage helpers — keys are scoped by user token hash
// ---------------------------------------------------------------------------

const MAX_HISTORY = 20;

/** Derive a short hash from the current API token for storage key scoping. */
function _tokenPrefix(): string {
  const token = getApiToken();
  if (!token) return "default";
  // Simple DJB2 hash — deterministic, fast, no crypto needed for a storage key
  let h = 5381;
  for (let i = 0; i < token.length; i++) {
    h = ((h << 5) + h + token.charCodeAt(i)) >>> 0;
  }
  return h.toString(36);
}

function _ssKey(): string { return `atlas_wb_${_tokenPrefix()}`; }
function _lsKey(): string { return `atlas_ch_${_tokenPrefix()}`; }

interface PersistedState {
  messages: ChatMessage[];
  sessionId?: string;
  config: ScreeningConfig;
  conditionSummary: string;
  candidates: StrongStock[];
  lastFetchKey: string;
  watchedTickers?: string[];
}

function saveToSession(state: PersistedState) {
  try {
    sessionStorage.setItem(_ssKey(), JSON.stringify(state));
  } catch {
    /* quota exceeded – ignore */
  }
}

function loadFromSession(): PersistedState | null {
  try {
    const raw = sessionStorage.getItem(_ssKey());
    if (!raw) return null;
    return JSON.parse(raw) as PersistedState;
  } catch {
    return null;
  }
}

function loadHistory(): ChatSession[] {
  try {
    const raw = localStorage.getItem(_lsKey());
    if (!raw) return [];
    return JSON.parse(raw) as ChatSession[];
  } catch {
    return [];
  }
}

function persistHistory(sessions: ChatSession[]) {
  try {
    localStorage.setItem(_lsKey(), JSON.stringify(sessions.slice(0, MAX_HISTORY)));
  } catch { /* quota exceeded */ }
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const WorkbenchContext = createContext<WorkbenchState | null>(null);

export function useWorkbench(): WorkbenchState {
  const ctx = useContext(WorkbenchContext);
  if (!ctx) throw new Error("useWorkbench must be used within WorkbenchProvider");
  return ctx;
}

export function WorkbenchProvider({ children }: { children: ReactNode }) {
  // ── Always initialise with static defaults (same on server + client) ────
  // loadFromSession() must NOT be called during render — sessionStorage is
  // unavailable on the server, causing a hydration mismatch.
  // Restoration happens in useEffect after hydration completes.

  // Chat
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [showWelcome, setShowWelcome] = useState(true);

  // Config
  const [config, setConfig] = useState<ScreeningConfig>(DEFAULT_CONFIG);

  // Candidates
  const [candidates, setCandidates] = useState<StrongStock[]>([]);
  const [candidatesByMarket, setCandidatesByMarket] = useState<Record<string, StrongStock[]>>({});
  const setCandidatesForMarket = useCallback((market: string, stocks: StrongStock[]) => {
    setCandidatesByMarket((prev) => ({ ...prev, [market]: stocks }));
  }, []);
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [conditionSummary, setConditionSummary] = useState("");
  const [candidatesStale, setCandidatesStale] = useState(false);

  // Analysis
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [analysisCache, setAnalysisCache] = useState<Record<string, StockAnalysis>>({});
  const [analysisLoadingTickers, setAnalysisLoadingTickers] = useState<Set<string>>(new Set());

  const setAnalysisForTicker = useCallback((ticker: string, a: StockAnalysis) => {
    setAnalysisCache((prev) => ({ ...prev, [ticker]: a }));
  }, []);
  const clearAnalysisForTicker = useCallback((ticker: string) => {
    setAnalysisCache((prev) => {
      const next = { ...prev };
      delete next[ticker];
      return next;
    });
  }, []);
  const setTickerAnalysisLoading = useCallback((ticker: string, loading: boolean) => {
    setAnalysisLoadingTickers((prev) => {
      const next = new Set(prev);
      if (loading) next.add(ticker); else next.delete(ticker);
      return next;
    });
  }, []);

  // Cache key for dedup
  const [lastFetchKey, setLastFetchKey] = useState("");

  // Watchlist
  const [watchedTickers, setWatchedTickers] = useState<Set<string>>(new Set());

  // Multi-ticker analysis queue
  const [pendingAnalysisTickers, setPendingAnalysisTickers] = useState<string[]>([]);

  // Agent tasks (persisted across page switches)
  const [agentTasks, setAgentTasks] = useState<TaskSpec[]>([]);
  const [agentTasksLoaded, setAgentTasksLoaded] = useState(false);
  const [agentSelectedId, setAgentSelectedId] = useState<string | null>(null);
  const [agentCycles, setAgentCycles] = useState<CycleResult[]>([]);
  const [agentRunningTasks, setAgentRunningTasks] = useState<Set<string>>(new Set());
  const [agentDashboard, setAgentDashboard] = useState<Record<string, unknown> | null>(null);

  const markCandidatesStale = useCallback(() => setCandidatesStale(true), []);

  // Chat history
  const [chatHistory, setChatHistory] = useState<ChatSession[]>([]);

  // Cross-page unread notification
  const [hasUnreadChat, setHasUnreadChat] = useState(false);
  const pushAgentMessage = useCallback((content: string, markUnread = false) => {
    setMessages((prev) => [...prev, { role: "assistant" as const, content }]);
    setShowWelcome(false);
    if (markUnread) setHasUnreadChat(true);
  }, [setMessages, setShowWelcome]);

  const _buildCurrentSession = useCallback((): ChatSession | null => {
    if (messages.length === 0) return null;
    const firstUser = messages.find((m) => m.role === "user");
    const title = firstUser?.content?.slice(0, 40) || "新对话";
    return {
      id: sessionId || crypto.randomUUID(),
      title,
      messages,
      sessionId,
      config,
      updatedAt: Date.now(),
    };
  }, [messages, sessionId, config]);

  const saveAndNewSession = useCallback(() => {
    const current = _buildCurrentSession();
    if (current) {
      setChatHistory((prev) => {
        const filtered = prev.filter((s) => s.id !== current.id);
        const next = [current, ...filtered].slice(0, MAX_HISTORY);
        persistHistory(next);
        return next;
      });
    }
    setMessages([]);
    setSessionId(undefined);
    setShowWelcome(true);
  }, [_buildCurrentSession, setMessages, setSessionId, setShowWelcome]);

  const switchToSession = useCallback((id: string) => {
    // Save current first
    const current = _buildCurrentSession();
    setChatHistory((prev) => {
      let list = [...prev];
      if (current) {
        list = list.filter((s) => s.id !== current.id);
        list.unshift(current);
      }
      const target = list.find((s) => s.id === id);
      if (!target) return list;
      // Load target into active state
      setMessages(target.messages);
      setSessionId(target.sessionId);
      setConfig(target.config);
      setShowWelcome(false);
      // Remove target from history
      const next = list.filter((s) => s.id !== id).slice(0, MAX_HISTORY);
      persistHistory(next);
      return next;
    });
  }, [_buildCurrentSession, setMessages, setSessionId, setConfig, setShowWelcome]);

  const deleteSession = useCallback((id: string) => {
    setChatHistory((prev) => {
      const next = prev.filter((s) => s.id !== id);
      persistHistory(next);
      return next;
    });
  }, []);

  // ── Restore from sessionStorage after hydration ──────────────────────────
  const hydrated = useRef(false);
  useEffect(() => {
    if (hydrated.current) return;
    hydrated.current = true;
    const saved = loadFromSession();
    if (!saved) return;
    if (saved.messages?.length) {
      setMessages(saved.messages);
      setShowWelcome(false);
    }
    if (saved.sessionId) setSessionId(saved.sessionId);
    if (saved.config) setConfig(saved.config);
    if (saved.candidates?.length) {
      setCandidates(saved.candidates);
      if (saved.conditionSummary) setConditionSummary(saved.conditionSummary);
      if (saved.lastFetchKey) setLastFetchKey(saved.lastFetchKey);
    }
    if (saved.watchedTickers?.length) setWatchedTickers(new Set(saved.watchedTickers));
    // Load chat history from localStorage
    setChatHistory(loadHistory());
  }, []);

  // ── Persist to sessionStorage on meaningful state changes ────────────────
  useEffect(() => {
    if (!hydrated.current) return;
    saveToSession({
      messages,
      sessionId,
      config,
      conditionSummary,
      candidates,
      lastFetchKey,
      watchedTickers: Array.from(watchedTickers),
    });
  }, [messages, sessionId, config, conditionSummary, candidates, lastFetchKey, watchedTickers]);

  return (
    <WorkbenchContext.Provider
      value={{
        messages,
        setMessages,
        sessionId,
        setSessionId,
        showWelcome,
        setShowWelcome,
        config,
        setConfig,
        candidates,
        setCandidates,
        candidatesByMarket,
        setCandidatesForMarket,
        candidatesLoading,
        setCandidatesLoading,
        conditionSummary,
        setConditionSummary,
        candidatesStale,
        markCandidatesStale,
        selectedTicker,
        setSelectedTicker,
        analysisCache,
        setAnalysisForTicker,
        clearAnalysisForTicker,
        analysisLoadingTickers,
        setTickerAnalysisLoading,
        lastFetchKey,
        setLastFetchKey,
        watchedTickers,
        setWatchedTickers,
        pendingAnalysisTickers,
        setPendingAnalysisTickers,
        chatHistory,
        saveAndNewSession,
        switchToSession,
        deleteSession,
        hasUnreadChat,
        setHasUnreadChat,
        pushAgentMessage,
        agentTasks,
        setAgentTasks,
        agentTasksLoaded,
        setAgentTasksLoaded,
        agentSelectedId,
        setAgentSelectedId,
        agentCycles,
        setAgentCycles,
        agentRunningTasks,
        setAgentRunningTasks,
        agentDashboard,
        setAgentDashboard,
      }}
    >
      {children}
    </WorkbenchContext.Provider>
  );
}
