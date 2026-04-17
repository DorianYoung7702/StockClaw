"use client";

import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Bot, User, Shield } from "lucide-react";
import { cn, cleanLLMOutput } from "@/lib/utils";
import type { ChatMessage } from "@/lib/types";

interface MessageBubbleProps {
  message: ChatMessage;
  isStreaming?: boolean;
}

export function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const isSystem = message.isSystem || message.role === "system";
  const cleaned = useMemo(
    () => (isUser ? message.content : cleanLLMOutput(message.content)),
    [isUser, message.content]
  );
  const isThinking = !isUser && !isSystem && isStreaming && !cleaned;

  // System notification (harness events)
  if (isSystem) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 animate-fade-in">
        <Shield className="w-3 h-3 text-amber-400 shrink-0" />
        <span className="text-[11px] text-amber-300/80">{message.content}</span>
      </div>
    );
  }

  return (
    <div className={cn("flex gap-3 animate-fade-in", isUser ? "flex-row-reverse" : "")}>
      {/* Avatar */}
      <div
        className={cn(
          "shrink-0 w-7 h-7 rounded-lg flex items-center justify-center mt-0.5",
          isUser ? "bg-surface-2" : "bg-brand/15"
        )}
      >
        {isUser ? (
          <User className="w-3.5 h-3.5 text-zinc-400" />
        ) : (
          <Bot className={cn("w-3.5 h-3.5 text-brand", isThinking && "animate-pulse")} />
        )}
      </div>

      {/* Content */}
      <div
        className={cn(
          "max-w-[85%] rounded-xl px-4 py-2.5 text-sm leading-relaxed",
          isUser
            ? "bg-brand/10 text-theme-primary border border-brand/20"
            : "bg-surface-1 text-theme-secondary border-theme prose prose-sm prose-zinc dark:prose-invert max-w-none"
        )}
      >
        {isThinking ? (
          <div className="flex items-center gap-1 py-0.5">
            <span className="w-1.5 h-1.5 rounded-full bg-brand/60 animate-bounce [animation-delay:0ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-brand/60 animate-bounce [animation-delay:150ms]" />
            <span className="w-1.5 h-1.5 rounded-full bg-brand/60 animate-bounce [animation-delay:300ms]" />
          </div>
        ) : isUser ? (
          <div className="whitespace-pre-wrap">{cleaned}</div>
        ) : (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{cleaned}</ReactMarkdown>
        )}
        {isStreaming && cleaned && (
          <span className="inline-block w-1.5 h-4 bg-brand/60 rounded-sm ml-0.5 animate-pulse" />
        )}
      </div>
    </div>
  );
}
