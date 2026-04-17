import type {
  StrongStock,
  StockAnalysis,
  WatchlistGroup,
  SubscriptionPlan,
  ChatMessage,
} from "./types";

/* --------------------------------------------------------
   Mock: Candidate stocks
   -------------------------------------------------------- */
export const MOCK_CANDIDATES: StrongStock[] = [
  { ticker: "NVDA", name: "NVIDIA Corp", reason: "AI 芯片龙头，20日RSI 72，多周期动量排名前3", rsi: 72, momentum_score: 94, avg_volume: 48_000_000, risk_level: "medium", trend: "strong", market_type: "us_stock" },
  { ticker: "AVGO", name: "Broadcom Inc", reason: "VMware 整合完成，数据中心业务加速增长", rsi: 65, momentum_score: 88, avg_volume: 12_000_000, risk_level: "low", trend: "strong", market_type: "us_stock" },
  { ticker: "META", name: "Meta Platforms", reason: "广告收入反弹+AI投资加速，利润率持续改善", rsi: 61, momentum_score: 82, avg_volume: 22_000_000, risk_level: "low", trend: "strong", market_type: "us_stock" },
  { ticker: "TSM", name: "台积电 ADR", reason: "AI 晶圆代工需求强劲，产能利用率回升至95%", rsi: 58, momentum_score: 78, avg_volume: 18_000_000, risk_level: "medium", trend: "strong", market_type: "us_stock" },
  { ticker: "AMAT", name: "Applied Materials", reason: "半导体设备需求回暖，先进制程订单增加", rsi: 55, momentum_score: 75, avg_volume: 8_000_000, risk_level: "medium", trend: "neutral", market_type: "us_stock" },
  { ticker: "PLTR", name: "Palantir Tech", reason: "AIP 平台商业化加速，政府+商业双轮驱动", rsi: 68, momentum_score: 86, avg_volume: 45_000_000, risk_level: "high", trend: "strong", market_type: "us_stock" },
  { ticker: "CRWD", name: "CrowdStrike", reason: "网络安全支出增加，ARR 加速增长", rsi: 60, momentum_score: 77, avg_volume: 6_500_000, risk_level: "medium", trend: "strong", market_type: "us_stock" },
  { ticker: "ARM", name: "ARM Holdings", reason: "AI 边缘计算催化，授权收入超预期", rsi: 70, momentum_score: 90, avg_volume: 15_000_000, risk_level: "high", trend: "strong", market_type: "us_stock" },
  { ticker: "MRVL", name: "Marvell Tech", reason: "定制AI芯片需求旺盛，数据中心收入翻倍", rsi: 53, momentum_score: 71, avg_volume: 10_000_000, risk_level: "medium", trend: "neutral", market_type: "us_stock" },
  { ticker: "SMCI", name: "Super Micro", reason: "AI 服务器出货增长，液冷方案市占率领先", rsi: 48, momentum_score: 65, avg_volume: 20_000_000, risk_level: "high", trend: "neutral", market_type: "us_stock" },
];

/* --------------------------------------------------------
   Mock: Stock analysis
   -------------------------------------------------------- */
export const MOCK_ANALYSIS: Record<string, StockAnalysis> = {
  NVDA: {
    ticker: "NVDA",
    name: "NVIDIA Corporation",
    conclusion: "AI 基础设施核心受益者，数据中心收入占比超 80%。短期估值偏高但增长确定性强，适合中长期关注。",
    recommendation: "关注",
    sections: [
      { title: "增长分析", score: 92, summary: "数据中心收入同比增长 122%，游戏业务恢复增长", details: ["FY2025 Q3 数据中心收入 $14.5B (+122% YoY)", "游戏收入 $2.9B (+15% YoY)", "汽车+机器人业务 $346M (+72% YoY)"] },
      { title: "盈利分析", score: 88, summary: "毛利率稳定在 75% 以上，运营杠杆持续释放", details: ["GAAP 毛利率 75.0%", "Non-GAAP 运营利润率 65.2%", "自由现金流 $7.3B (单季)"] },
      { title: "资产负债", score: 80, summary: "资产负债表健康，净现金充裕", details: ["现金及等价物 $18.3B", "总负债 $12.9B", "净现金 $5.4B", "Debt/Equity 0.41x"] },
      { title: "现金流", score: 85, summary: "经营性现金流强劲，资本开支可控", details: ["经营现金流 TTM $28.1B", "资本支出 TTM $2.1B", "自由现金流转换率 92%"] },
    ],
    peers: [
      { ticker: "AMD", name: "AMD", pe: 45.2, pb: 4.1, roe: 9.2, market_cap: "$238B" },
      { ticker: "AVGO", name: "Broadcom", pe: 35.8, pb: 12.3, roe: 35.1, market_cap: "$620B" },
      { ticker: "INTC", name: "Intel", pe: -8.5, pb: 1.1, roe: -3.2, market_cap: "$110B" },
      { ticker: "NVDA", name: "NVIDIA", pe: 65.3, pb: 52.1, roe: 82.3, market_cap: "$2.8T" },
    ],
    risks: ["估值处于历史高位 (P/E 65x)", "AI 资本支出周期性风险", "中国市场出口限制持续", "客户集中度偏高 (前5大客户占 40%)"],
    updated_at: new Date().toISOString(),
  },
  META: {
    ticker: "META",
    name: "Meta Platforms Inc",
    conclusion: "广告业务复苏明显，Reels 变现加速。AI 投入巨大但已初见成效，利润率持续改善。",
    recommendation: "关注",
    sections: [
      { title: "增长分析", score: 85, summary: "广告收入同比增长 24%，用户增长稳定", details: ["Q3 总收入 $40.6B (+24% YoY)", "DAP 3.29B (+5% YoY)", "ARPU $13.12 (+19% YoY)"] },
      { title: "盈利分析", score: 90, summary: "效率年成果显现，运营利润率回升", details: ["运营利润率 43%", "净利润 $15.7B", "每股收益 $6.03 (+73% YoY)"] },
      { title: "资产负债", score: 88, summary: "零负债运营，现金储备充裕", details: ["现金 $70.9B", "零长期债务", "股东权益 $153B"] },
      { title: "现金流", score: 87, summary: "自由现金流充沛，支撑大规模回购", details: ["经营现金流 $19.4B (单季)", "资本支出 $9.2B", "回购 $8.9B (单季)"] },
    ],
    peers: [
      { ticker: "GOOGL", name: "Alphabet", pe: 24.1, pb: 7.2, roe: 31.2, market_cap: "$2.1T" },
      { ticker: "SNAP", name: "Snap", pe: -25.0, pb: 8.5, roe: -18.0, market_cap: "$18B" },
      { ticker: "META", name: "Meta", pe: 28.5, pb: 8.9, roe: 35.8, market_cap: "$1.5T" },
    ],
    risks: ["AI 基建资本支出持续攀升", "Reality Labs 持续亏损 ($4.5B/季)", "监管风险 (反垄断+数据隐私)", "Reels 变现天花板待验证"],
    updated_at: new Date().toISOString(),
  },
};

/* Default analysis for any ticker not in MOCK_ANALYSIS */
export function getMockAnalysis(ticker: string): StockAnalysis {
  if (MOCK_ANALYSIS[ticker]) return MOCK_ANALYSIS[ticker];
  return {
    ticker,
    name: `${ticker} Inc`,
    conclusion: "数据加载中，请稍后查看完整基本面分析报告。",
    recommendation: "观察",
    sections: [
      { title: "增长分析", score: 65, summary: "近期营收增速平稳", details: ["同比增长 12%", "环比持平"] },
      { title: "盈利分析", score: 60, summary: "利润率保持稳定", details: ["毛利率 45%", "净利率 18%"] },
      { title: "资产负债", score: 70, summary: "负债水平合理", details: ["Debt/Equity 0.6x", "流动比率 2.1"] },
      { title: "现金流", score: 68, summary: "现金流为正", details: ["自由现金流 $2.1B"] },
    ],
    peers: [],
    risks: ["需更多数据验证"],
    updated_at: new Date().toISOString(),
  };
}

/* --------------------------------------------------------
   Mock: Watchlist groups
   -------------------------------------------------------- */
export const MOCK_WATCHLIST_GROUPS: WatchlistGroup[] = [
  {
    id: "ai-watch",
    name: "AI 观察组",
    color: "#10b981",
    items: [
      { ticker: "NVDA", note: "关注 Q4 财报指引", added_at: "2025-01-15T08:30:00Z" },
      { ticker: "PLTR", note: "AIP 商业化进展", added_at: "2025-01-12T10:00:00Z" },
      { ticker: "ARM", note: "IPO 锁定期解除后走势", added_at: "2025-01-10T09:15:00Z" },
    ],
  },
  {
    id: "hk-dividend",
    name: "港股红利",
    color: "#f59e0b",
    items: [
      { ticker: "0005.HK", note: "汇丰分红稳定", added_at: "2025-01-08T03:30:00Z" },
      { ticker: "0388.HK", note: "港交所交易量回升", added_at: "2025-01-05T06:00:00Z" },
    ],
  },
  {
    id: "short-term",
    name: "短线观察",
    color: "#ef4444",
    items: [
      { ticker: "SMCI", note: "财报后观察反弹力度", added_at: "2025-01-14T14:00:00Z" },
      { ticker: "MRVL", note: "定制芯片订单催化", added_at: "2025-01-13T11:00:00Z" },
    ],
  },
];

/* --------------------------------------------------------
   Mock: Chat history
   -------------------------------------------------------- */
export const MOCK_CHAT: ChatMessage[] = [
  { role: "user", content: "帮我找最近走势强的美股 AI 芯片股，大盘股为主" },
  { role: "assistant", content: "好的，我已根据以下条件筛选：\n\n• 市场：美股\n• 板块：AI / 半导体\n• 市值：大盘（>$100B）\n• RSI(20) > 50\n• 多周期动量评分前10\n\n已生成 10 只候选股，请在中间面板查看。点击任意一只可查看详细基本面分析。" },
];

/* --------------------------------------------------------
   Mock: Quick prompts
   -------------------------------------------------------- */
export const QUICK_PROMPTS = [
  "给我看看美股强势股",
  "分析 NVDA 的基本面",
  "分析苹果最近财报表现",
  "港股有哪些值得关注的强势股",
  "对比 TSLA 和 NVDA 基本面",
  "目前大盘环境怎么样",
];

export const QUICK_PROMPT_CATEGORIES: { label: string; icon: string; prompts: string[] }[] = [
  {
    label: "强势股筛选",
    icon: "trending",
    prompts: ["给我看看美股强势股", "港股有哪些强势股", "看看 ETF 有什么强势的"],
  },
  {
    label: "个股分析",
    icon: "analysis",
    prompts: ["分析 NVDA 的基本面", "分析苹果最近财报表现", "对比 TSLA 和 NVDA"],
  },
  {
    label: "市场概览",
    icon: "market",
    prompts: ["目前大盘环境怎么样", "最近有什么利好消息"],
  },
];

export const FOLLOWUP_PROMPTS = [
  "分析一下AAPL",
  "帮我分析腾讯",
  "NVDA加入观察组",
  "对比AAPL和MSFT",
  "筛选港股强势股",
  "看看美股有什么强势的",
  "把RSI阈值改成55",
  "切换到ETF市场",
  "TSLA移出观察组",
  "排序改成20日涨幅",
  "筛选数量改为5只",
  "00700.HK加入观察组并分析",
];

/* --------------------------------------------------------
   Mock: Subscription plans
   -------------------------------------------------------- */
export const MOCK_PLANS: SubscriptionPlan[] = [
  {
    id: "free",
    name: "免费版",
    price: "¥0",
    period: "永久",
    features: [
      "每日 3 次候选股筛选",
      "基本面分析 5 次/日",
      "1 个观察组（最多 10 只）",
      "社区支持",
    ],
    highlighted: false,
    cta: "当前方案",
  },
  {
    id: "pro",
    name: "Pro",
    price: "¥99",
    period: "/月",
    features: [
      "无限候选股筛选",
      "无限基本面分析",
      "10 个观察组（每组 50 只）",
      "自定义筛选参数",
      "财报提醒推送",
      "API 访问",
      "优先客服",
    ],
    highlighted: true,
    cta: "升级到 Pro",
  },
  {
    id: "premium",
    name: "高级版",
    price: "¥299",
    period: "/月",
    features: [
      "Pro 全部功能",
      "深度文档 RAG 分析",
      "自定义 AI 模型",
      "团队协作（最多 5 人）",
      "每日自动推送报告",
      "专属客户经理",
      "SLA 99.9%",
    ],
    highlighted: false,
    cta: "联系销售",
  },
];
