"use client";

import { TrendingUp, BarChart3, Globe, Sparkles } from "lucide-react";
import { QUICK_PROMPT_CATEGORIES } from "@/lib/mock-data";

const ICON_MAP: Record<string, React.ReactNode> = {
  trending: <TrendingUp className="w-4 h-4" />,
  analysis: <BarChart3 className="w-4 h-4" />,
  market: <Globe className="w-4 h-4" />,
};

interface QuickPromptsProps {
  onSelect: (prompt: string) => void;
}

export function QuickPrompts({ onSelect }: QuickPromptsProps) {
  return (
    <div className="w-full max-w-[520px] space-y-3">
      {QUICK_PROMPT_CATEGORIES.map((cat) => (
        <div key={cat.label}>
          <div className="flex items-center gap-1.5 mb-1.5 px-1">
            <span className="text-brand/70">{ICON_MAP[cat.icon] || <Sparkles className="w-4 h-4" />}</span>
            <span className="text-xs font-medium text-theme-muted">{cat.label}</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {cat.prompts.map((prompt, i) => (
              <button
                key={i}
                onClick={() => onSelect(prompt)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-1 border border-zinc-800/50 text-xs text-zinc-400 hover:text-zinc-200 hover:border-brand/30 hover:bg-brand/5 transition-all duration-200"
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
