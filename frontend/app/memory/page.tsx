"use client";

import { useState, useEffect, useCallback } from "react";
import { Brain, Trash2, RefreshCw, AlertCircle, Sparkles, History, ChevronDown, ChevronRight } from "lucide-react";
import { getMemories, deleteMemory, clearAllMemories } from "@/lib/api";
import type { MemoryItem } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useUserId } from "@/lib/use-user-id";

const CATEGORY_META: Record<string, { label: string; icon: typeof Brain; color: string }> = {
  preference: { label: "投资偏好", icon: Sparkles, color: "text-amber-400" },
  analysis_history: { label: "分析历史", icon: History, color: "text-blue-400" },
  learned_pattern: { label: "行为模式", icon: Brain, color: "text-purple-400" },
};

function formatTime(ts: number) {
  return new Date(ts * 1000).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function MemoryPage() {
  const USER_ID = useUserId();
  const [memories, setMemories] = useState<Record<string, MemoryItem[]>>({});
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedCats, setExpandedCats] = useState<Set<string>>(new Set(["preference", "analysis_history"]));
  const [deleting, setDeleting] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);

  const load = useCallback(async () => {
    if (!USER_ID) return;  // wait for userId to resolve
    setLoading(true);
    setError(null);
    try {
      const res = await getMemories(USER_ID);
      setMemories(res.memories);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [USER_ID]);

  useEffect(() => { load(); }, [load]);

  const toggleCat = (cat: string) => {
    setExpandedCats((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  const handleDelete = async (category: string, key: string) => {
    const id = `${category}/${key}`;
    setDeleting(id);
    try {
      await deleteMemory(USER_ID, category, key);
      setMemories((prev) => {
        const next = { ...prev };
        next[category] = (next[category] || []).filter((m) => m.key !== key);
        if (next[category].length === 0) delete next[category];
        return next;
      });
      setTotal((t) => t - 1);
    } catch {
      /* best effort */
    } finally {
      setDeleting(null);
    }
  };

  const handleClearAll = async () => {
    if (!confirm("确定清空所有记忆？此操作不可撤销。")) return;
    setClearing(true);
    try {
      await clearAllMemories(USER_ID);
      setMemories({});
      setTotal(0);
    } catch {
      /* best effort */
    } finally {
      setClearing(false);
    }
  };

  const categories = Object.keys(memories);

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto px-4 py-6 sm:px-6 sm:py-12">
        {/* Header */}
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-8">
          <div>
            <div className="flex items-center gap-2.5 mb-1">
              <Brain className="w-6 h-6 text-brand" />
              <h1 className="text-2xl font-bold text-theme-primary">记忆管理</h1>
            </div>
            <p className="text-sm text-zinc-500">
              Atlas 从对话中学习你的偏好，并记录分析历史，为你提供个性化服务
            </p>
          </div>
          <div className="flex items-center gap-2 self-start sm:self-auto">
            <button
              onClick={load}
              disabled={loading}
              className="p-2 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-surface-2 transition-colors disabled:opacity-50"
              title="刷新"
            >
              <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
            </button>
            {total > 0 && (
              <button
                onClick={handleClearAll}
                disabled={clearing}
                className="px-3 py-1.5 rounded-lg text-xs text-red-400 hover:text-red-300 hover:bg-red-500/10 border border-red-500/20 transition-colors disabled:opacity-50"
              >
                {clearing ? "清空中..." : "清空全部"}
              </button>
            )}
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="flex items-center gap-2 text-sm text-red-400 bg-red-500/10 rounded-xl px-4 py-3 mb-6">
            <AlertCircle className="w-4 h-4 shrink-0" />
            {error}
          </div>
        )}

        {/* Empty state */}
        {!loading && total === 0 && !error && (
          <div className="text-center py-20">
            <Brain className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
            <p className="text-zinc-400 text-sm mb-1">暂无记忆</p>
            <p className="text-zinc-600 text-xs">
              与 Atlas 对话后，你的投资偏好和分析历史会自动出现在这里
            </p>
          </div>
        )}

        {/* Stats bar */}
        {total > 0 && (
          <div className="flex flex-wrap items-center gap-3 sm:gap-4 mb-6 text-xs text-zinc-500">
            <span>共 {total} 条记忆</span>
            {categories.map((cat) => {
              const meta = CATEGORY_META[cat] || { label: cat, icon: Brain, color: "text-zinc-400" };
              return (
                <span key={cat} className="flex items-center gap-1">
                  <meta.icon className={cn("w-3 h-3", meta.color)} />
                  {meta.label}: {memories[cat]?.length || 0}
                </span>
              );
            })}
          </div>
        )}

        {/* Category sections */}
        <div className="space-y-4">
          {categories.map((cat) => {
            const meta = CATEGORY_META[cat] || { label: cat, icon: Brain, color: "text-zinc-400" };
            const CatIcon = meta.icon;
            const expanded = expandedCats.has(cat);
            const items = memories[cat] || [];

            return (
              <div key={cat} className="rounded-xl border border-zinc-800/50 bg-surface-1 overflow-hidden">
                {/* Category header */}
                <button
                  onClick={() => toggleCat(cat)}
                  className="w-full flex items-center gap-3 px-4 sm:px-5 py-3.5 hover:bg-surface-2 transition-colors"
                >
                  {expanded ? (
                    <ChevronDown className="w-4 h-4 text-zinc-500" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-zinc-500" />
                  )}
                  <CatIcon className={cn("w-4 h-4", meta.color)} />
                  <span className="text-sm font-medium text-theme-primary">{meta.label}</span>
                  <span className="text-xs text-zinc-500 ml-auto">{items.length} 条</span>
                </button>

                {/* Items */}
                {expanded && (
                  <div className="border-t border-zinc-800/30">
                    {items.map((item) => (
                      <div
                        key={item.key}
                        className="flex items-start gap-3 px-4 sm:px-5 py-3 border-b border-zinc-800/20 last:border-b-0 hover:bg-surface-2/50 transition-colors group"
                      >
                        <div className="flex-1 min-w-0">
                          <div className="flex flex-wrap items-center gap-2 mb-0.5">
                            <span className="text-xs font-mono text-zinc-500 truncate max-w-[160px] sm:max-w-[200px]">
                              {item.key}
                            </span>
                            <span className="text-[10px] text-zinc-600">
                              {formatTime(item.updated_at)}
                            </span>
                          </div>
                          <p className="text-sm text-zinc-300 leading-relaxed">{item.content}</p>
                        </div>
                        <button
                          onClick={() => handleDelete(cat, item.key)}
                          disabled={deleting === `${cat}/${item.key}`}
                          className="p-1.5 rounded-md text-zinc-600 hover:text-red-400 hover:bg-red-500/10 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-all shrink-0 disabled:opacity-50"
                          title="删除"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
