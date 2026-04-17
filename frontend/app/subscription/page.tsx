"use client";

import { Check, Zap, Crown, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { MOCK_PLANS } from "@/lib/mock-data";

const PLAN_ICONS: Record<string, typeof Zap> = {
  free: Sparkles,
  pro: Zap,
  premium: Crown,
};

export default function SubscriptionPage() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto px-4 py-6 sm:px-6 sm:py-12">
        {/* Header */}
        <div className="text-center mb-8 sm:mb-12">
          <h1 className="text-2xl font-bold text-theme-primary mb-2">选择适合你的方案</h1>
          <p className="text-sm text-zinc-500 max-w-md mx-auto">
            从免费版开始，随时升级获取更强大的 AI 选股和基本面分析能力
          </p>
        </div>

        {/* Plan cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 sm:gap-5">
          {MOCK_PLANS.map((plan) => {
            const Icon = PLAN_ICONS[plan.id] || Sparkles;
            return (
              <div
                key={plan.id}
                className={cn(
                  "relative rounded-2xl p-5 sm:p-6 border transition-all duration-300",
                  plan.highlighted
                    ? "bg-gradient-to-b from-brand/10 to-surface-1 border-brand/30 shadow-lg shadow-brand/5 scale-[1.02]"
                    : "bg-surface-1 border-zinc-800/50 hover:border-zinc-700"
                )}
              >
                {plan.highlighted && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full bg-brand text-white text-[11px] font-medium">
                    推荐
                  </div>
                )}

                {/* Plan icon & name */}
                <div className="flex items-center gap-2 mb-4">
                  <div
                    className={cn(
                      "w-9 h-9 rounded-xl flex items-center justify-center",
                      plan.highlighted ? "bg-brand/20" : "bg-surface-2"
                    )}
                  >
                    <Icon
                      className={cn(
                        "w-4.5 h-4.5",
                        plan.highlighted ? "text-brand" : "text-zinc-400"
                      )}
                    />
                  </div>
                  <h3 className="text-base font-semibold text-theme-primary">{plan.name}</h3>
                </div>

                {/* Price — hidden until backend subscription API is ready */}
                <div className="mb-5">
                  <span className="text-lg font-semibold text-zinc-500">即将推出</span>
                </div>

                {/* CTA — disabled until pricing is live */}
                <button
                  disabled
                  className={cn(
                    "w-full py-2.5 rounded-xl text-sm font-medium transition-all duration-200 mb-6 cursor-not-allowed",
                    plan.id === "free"
                      ? "bg-surface-2 text-zinc-400"
                      : "bg-surface-2 text-zinc-500 border border-zinc-700/50"
                  )}
                >
                  {plan.id === "free" ? "当前方案" : "敬请期待"}
                </button>

                {/* Features */}
                <ul className="space-y-2.5">
                  {plan.features.map((feature, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm">
                      <Check
                        className={cn(
                          "w-4 h-4 shrink-0 mt-0.5",
                          plan.highlighted ? "text-brand" : "text-zinc-500"
                        )}
                      />
                      <span className="text-zinc-300">{feature}</span>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>

        {/* Current plan status */}
        <div className="mt-10 rounded-xl bg-surface-1 border border-zinc-800/50 p-5">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-medium text-theme-primary">当前方案：免费版</h3>
              <p className="text-xs text-zinc-500 mt-0.5">所有功能开放中 · 订阅体系上线后将同步显示用量</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
