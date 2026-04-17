"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { cn, cleanLLMOutput } from "@/lib/utils";
import type { AnalysisSection } from "@/lib/types";

interface AnalysisSectionCardProps {
  section: AnalysisSection;
  defaultOpen?: boolean;
}

export function AnalysisSectionCard({ section, defaultOpen = false }: AnalysisSectionCardProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-xl bg-surface-1 border border-zinc-800/50 overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-surface-2/50 transition-colors"
      >
        <span className="text-sm font-medium text-zinc-200">{section.title}</span>
        <motion.div
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.25, ease: "easeInOut" }}
        >
          <ChevronDown className="w-4 h-4 text-zinc-500" />
        </motion.div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 pt-1 border-t border-zinc-800/30">
              <div className="text-sm text-zinc-300 mb-3 prose prose-sm prose-zinc dark:prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{cleanLLMOutput(section.summary)}</ReactMarkdown>
              </div>
              <ul className="space-y-1.5">
                {section.details.filter((d) => !d.endsWith("N/A")).map((detail, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-zinc-400">
                    <span className="w-1 h-1 rounded-full bg-brand/60 mt-1.5 shrink-0" />
                    <span className="prose prose-xs prose-zinc dark:prose-invert max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{cleanLLMOutput(detail)}</ReactMarkdown>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
