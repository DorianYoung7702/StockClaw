import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Strip <think>…</think> blocks and JSON metadata prefixes from LLM output */
export function cleanLLMOutput(text: string): string {
  let out = text;
  out = out.replace(/<think>[\s\S]*?<\/think>\s*/g, "");
  out = out.replace(/<think>[\s\S]*$/g, "");
  out = out.replace(/^\s*\{[^}]*"intent"\s*:\s*"[^"]*"[^}]*\}\s*/g, "");
  return out.trim();
}
