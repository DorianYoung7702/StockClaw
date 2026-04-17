"use client";

import { useMemo } from "react";
import { MessageCircle } from "lucide-react";
import { FOLLOWUP_PROMPTS } from "@/lib/mock-data";

interface FollowupPromptsProps {
  onSelect: (prompt: string) => void;
  disabled?: boolean;
  count?: number;
}

function pickRandom<T>(arr: T[], n: number): T[] {
  const shuffled = [...arr].sort(() => Math.random() - 0.5);
  return shuffled.slice(0, n);
}

export function FollowupPrompts({ onSelect, disabled, count = 3 }: FollowupPromptsProps) {
  const prompts = useMemo(() => pickRandom(FOLLOWUP_PROMPTS, count), [count]);

  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {prompts.map((prompt, i) => (
        <button
          key={`${prompt}-${i}`}
          onClick={() => onSelect(prompt)}
          disabled={disabled}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-surface-2/60 border border-zinc-800/40 text-[11px] text-zinc-500 hover:text-zinc-300 hover:border-zinc-700 hover:bg-surface-2 transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <MessageCircle className="w-2.5 h-2.5" />
          {prompt}
        </button>
      ))}
    </div>
  );
}
