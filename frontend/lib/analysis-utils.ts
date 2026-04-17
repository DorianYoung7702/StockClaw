/**
 * Shared utility: map backend FundamentalReport (structured JSON) → frontend StockAnalysis.
 * Used by both workbench page.tsx and watchlist/page.tsx.
 */

import type { StockAnalysis } from "@/lib/types";

const fmtPct = (v: unknown) => (v != null ? `${(Math.abs(Number(v)) < 1 ? Number(v) * 100 : Number(v)).toFixed(1)}%` : "N/A");
const fmtNum = (v: unknown) => {
  if (v == null) return "N/A";
  const n = Number(v);
  if (Math.abs(n) >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  return n.toFixed(2);
};
const fmtRatio = (v: unknown) => (v != null ? Number(v).toFixed(2) : "N/A");
const dimScore = (obj: Record<string, unknown> | undefined, fields: string[]) => {
  if (!obj) return 50;
  const filled = fields.filter((f) => obj[f] != null).length;
  return Math.min(95, 50 + Math.round((filled / fields.length) * 45));
};

export function mapStructuredToAnalysis(
  ticker: string,
  structured: Record<string, unknown> | null,
  report: string,
  errors: string[],
  evidenceChain: ReadonlyArray<Record<string, unknown>> | StockAnalysis["evidence_chain"] = [],
  retrievalDebug: Record<string, unknown> | StockAnalysis["retrieval_debug"] = {},
): StockAnalysis {
  const normalizedEvidence = (evidenceChain || []).map((item) => ({
    id: String(item?.id || ""),
    source_type: String(item?.source_type || "unknown"),
    source_label: String(item?.source_label || item?.source_type || "source"),
    ticker: item?.ticker ? String(item.ticker) : undefined,
    title: String(item?.title || item?.doc_label || item?.source_label || "Evidence"),
    snippet: String(item?.snippet || ""),
    score: item?.score != null ? Number(item.score) : undefined,
    published_at: item?.published_at ? String(item.published_at) : undefined,
    url: item?.url ? String(item.url) : undefined,
    doc_label: item?.doc_label ? String(item.doc_label) : undefined,
    metadata: item?.metadata && typeof item.metadata === "object" ? item.metadata as Record<string, unknown> : undefined,
  }));
  const normalizedRetrievalDebug = (retrievalDebug || {}) as StockAnalysis["retrieval_debug"];

  if (!structured) {
    return {
      ticker,
      name: ticker,
      conclusion: report || "分析完成",
      recommendation: "观察",
      sections: [{ title: "AI 分析报告", score: 70, summary: report || "", details: errors || [] }],
      peers: [],
      risks: errors || [],
      evidence_chain: normalizedEvidence,
      retrieval_debug: normalizedRetrievalDebug,
      updated_at: new Date().toISOString(),
    };
  }

  const s = structured;
  const prof = (s.profitability || {}) as Record<string, unknown>;
  const grow = (s.growth || {}) as Record<string, unknown>;
  const val = (s.valuation || {}) as Record<string, unknown>;
  const hlth = (s.financial_health || {}) as Record<string, unknown>;
  const sent = (s.news_sentiment || {}) as Record<string, unknown>;

  const sections: StockAnalysis["sections"] = [
    {
      title: "盈利分析",
      score: dimScore(prof, ["gross_margin", "operating_margin", "net_margin", "roe"]),
      summary: String(prof.summary || ""),
      details: [
        `毛利率 ${fmtPct(prof.gross_margin)}`,
        `营业利润率 ${fmtPct(prof.operating_margin)}`,
        `净利率 ${fmtPct(prof.net_margin)}`,
        `ROE ${fmtPct(prof.roe)}`,
        prof.roa != null ? `ROA ${fmtPct(prof.roa)}` : "",
      ].filter(Boolean),
    },
    {
      title: "增长分析",
      score: dimScore(grow, ["revenue_growth_yoy", "earnings_growth_yoy", "revenue_cagr_3y"]),
      summary: String(grow.summary || ""),
      details: [
        `营收同比增长 ${fmtPct(grow.revenue_growth_yoy)}`,
        `利润同比增长 ${fmtPct(grow.earnings_growth_yoy)}`,
        grow.revenue_cagr_3y != null ? `3年营收 CAGR ${fmtPct(grow.revenue_cagr_3y)}` : "",
      ].filter(Boolean),
    },
    {
      title: "估值分析",
      score: dimScore(val, ["pe_ratio", "pb_ratio", "ev_to_ebitda"]),
      summary: String(val.summary || ""),
      details: [
        `P/E ${fmtRatio(val.pe_ratio)}`,
        `P/B ${fmtRatio(val.pb_ratio)}`,
        val.ps_ratio != null ? `P/S ${fmtRatio(val.ps_ratio)}` : "",
        `EV/EBITDA ${fmtRatio(val.ev_to_ebitda)}`,
        val.peg_ratio != null ? `PEG ${fmtRatio(val.peg_ratio)}` : "",
      ].filter(Boolean),
    },
    {
      title: "资产负债",
      score: dimScore(hlth, ["debt_to_equity", "current_ratio", "free_cash_flow"]),
      summary: String(hlth.summary || ""),
      details: [
        `Debt/Equity ${fmtRatio(hlth.debt_to_equity)}`,
        `流动比率 ${fmtRatio(hlth.current_ratio)}`,
        hlth.quick_ratio != null ? `速动比率 ${fmtRatio(hlth.quick_ratio)}` : "",
        `自由现金流 ${fmtNum(hlth.free_cash_flow)}`,
      ].filter(Boolean),
    },
  ];

  if (sent.summary || sent.overall) {
    sections.push({
      title: "舆情分析",
      score: sent.overall === "positive" ? 80 : sent.overall === "negative" ? 35 : 55,
      summary: String(sent.summary || `整体情绪: ${sent.overall || "neutral"}`),
      details: ((sent.key_headlines || []) as string[]).map(String),
    });
  }

  const overview = (s.intelligence_overview as Record<string, unknown>)?.summary || "";
  const conclusion = String(overview || report?.slice(0, 300) || "分析完成");

  return {
    ticker,
    name: String(s.company_name || s.name || ticker),
    conclusion,
    recommendation: "观察",
    sections,
    peers: [],
    risks: Array.isArray(s.risk_factors) ? s.risk_factors.map(String) : (errors || []),
    evidence_chain: normalizedEvidence,
    retrieval_debug: normalizedRetrievalDebug,
    updated_at: new Date().toISOString(),
  };
}
