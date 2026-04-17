# Atlas Fundamental Intelligence Agent

基于 **LangChain + LangGraph** 的多 Agent **情报聚合**系统：典型用法是 **对强势股监控池 / 推荐名单中的指定 ticker 拉取并整理基本面与新闻情报**（财报、估值、同业、风险、催化剂等），输出结构化 JSON + Markdown。**不主动给出买卖或持仓类建议**（除非用户在对话中明确要求）。选股与池子构建由 `monitor/` 侧负责；本模块负责「给定代码 → 情报」。

**完整工作流程（LangGraph 节点、状态字段、API 与图的关系）见 [docs/LANGCHAIN_WORKFLOW.md](docs/LANGCHAIN_WORKFLOW.md)。**

## 架构概览

```
  Next.js Frontend :3000                    Cloudflare Tunnel (demo)
        │ fetch /api/*                              │
┌───────▼───────────────────────────────────────────▼─────────────┐
│                    FastAPI Server :8000                          │
│  /api/v1/chat   /api/v1/analyze   /api/v1/strong-stocks         │
│  /api/v1/watchlist   /api/v1/health   /api/v1/sessions          │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│         LangGraph Multi-Agent Orchestrator (17 节点)             │
│                                                                  │
│  parse_input ─┬→ resolve_symbol → [human_confirm]               │
│  (意图分类)    │       → retrieve_fundamental_rag                 │
│               │       → gather_data ──┐  (并行 fan-out)          │
│               │       → sentiment    ─┴→ synthesis               │
│               │                          → validate_result       │
│               │                          → reflect (LLM-as-Judge)│
│               │                          → render_output → END   │
│               ├→ strong_stocks → synthesis → … → END             │
│               ├→ plan → execute_step (循环) → synthesis → … → END│
│               ├→ update_config → END                             │
│               └→ chat → END                                      │
│                                                                  │
│  辅助节点: supervisor, watchlist_add                              │
└──────────────────────────────────────────────────────────────────┘
                            │
     ┌──────────┬───────────┼───────────┬──────────────┐
     ▼          ▼           ▼           ▼              ▼
┌────────┐ ┌────────┐ ┌─────────┐ ┌──────────┐ ┌────────────┐
│yfinance│ │ OpenBB │ │   FMP   │ │ monitor/ │ │ 本地快照    │
│ (默认)  │ │  SDK   │ │  API    │ │ (强势股)  │ │ (fallback) │
└────────┘ └────────┘ └─────────┘ └──────────┘ └────────────┘
```

## 核心特性

- **17 节点 LangGraph 状态机**：支持多路意图分支、并行 fan-out、条件循环
- **6 大高级特性**：
  - **Multi-Agent Delegation**：supervisor 节点协调子 Agent 路由
  - **Dynamic Planning**：plan → execute_step 循环处理多步复杂任务
  - **Reflection + Self-Critique**：LLM-as-Judge 对报告评分，低分自动修订
  - **Adaptive RAG**：会话内深度文档向量检索，按相关性注入分析上下文
  - **Intent Classification**：正则快速路径 + LLM fallback 的混合意图识别
  - **Human-in-the-Loop**：歧义 ticker 暂停等待用户确认
- **13 个金融数据工具**：三大财报、关键指标、公司概况、新闻情绪、同业对比、风险指标、催化剂、强势股、大盘环境、价格历史、技术分析、观察组、监控告警
- **4 种数据 Provider**：yfinance（默认）/ OpenBB / FMP / Mock，通过 `FINANCIAL_DATA_PROVIDER` 一键切换
- **数据快照保底**：`scripts/warm_demo.py` 预生成 JSON 快照，API 失败/限速时自动降级到本地缓存
- **公司名识别**：支持中文公司名（"英伟达"→NVDA）、港股代码（0700.HK）
- **结构化双输出**：`FundamentalReport` JSON + Markdown 报告同时输出
- **质量门控**：validate_result 节点检查 6 个分析维度覆盖度，数据不足自动标注
- **三模型支持**：MiniMax M2.7（默认）/ DeepSeek V3 / 智谱 GLM，通过配置一键切换
- **SSE 流式响应**：实时返回 Agent 思考过程、工具调用进度和结果
- **Next.js 前端**：现代化 UI，支持聊天、分析、强势股筛选、观察组管理
- **Evaluation Pipeline**：pytest 评估套件，含意图准确率、报告结构校验、LLM Judge 评分
- **本地 CLI 测试**：无需启动 FastAPI 即可运行分析

## 快速开始

### 1. 安装依赖

```bash
cd langchain_agent
pip install -e ".[dev]"
```

### 2. 配置环境变量

```bash
cp env.template .env
```

编辑 `.env` 文件，填入 API Key（**不要在值后加注释，不要用引号包裹值**）：

```
LLM_PROVIDER=minimax
MINIMAX_API_KEY=你的MiniMax密钥
```

必填项（默认 MiniMax）：
- `MINIMAX_API_KEY`：MiniMax 开放平台 API Key（Bearer，无需 Group ID）

可选：
- `TOOL_CALLING_MODEL` / `REASONING_MODEL`：默认均为 `MiniMax-M2.7`，可改为 `MiniMax-M2.7-highspeed` 等（以控制台为准）
- 使用 DeepSeek：`LLM_PROVIDER=deepseek` 并设置 `DEEPSEEK_API_KEY`，模型名建议 `TOOL_CALLING_MODEL=deepseek-chat`
- 使用智谱：`LLM_PROVIDER=zhipu`，`pip install 'atlas-langchain-agent[zhipu]'`，并设置 `ZHIPU_API_KEY`

可选项：
- `OPENBB_TOKEN`：OpenBB 平台 Token（部分数据 API 需要）
- `ATLAS_FORCE_RESPONSE_LOCALE`：`auto`（默认，跟随用户语言）或 `zh`（**测试/演示**：强制全链路简体中文，含 JSON 内可读字段）

### 回答口径（情报边界）

文档里说的**不是**「选股策略 / 交易策略」，而是 **模型怎么回答的边界**（给强势股做基本面信息时，仍只陈述事实与公开框架，不把情报写成对你的仓位或资金的建议）。

- **产品场景**：`openbb/` 产出强势股列表 → 用户或 OpenClaw 选定某只代码 → 本 Agent **按该代码输出指定基本面情报**（与是否「强势」无关的通用分析管线）。
- **具体情况 / 「我该怎么办」**：在闲聊或追问里，模型只输出**常识级、一般性**说明，**不对用户个人情景做针对性解读**（不假设资金、仓位、期限、风险偏好）。
- **中文与回答口径验收**：**以 CLI 为准**（见下文 `python cli.py … --zh`）。`ATLAS_FORCE_RESPONSE_LOCALE=zh` 与 `--zh` 等价；API 服务启动前写入 `.env` 也同样生效。

### 3. 本地 CLI 测试（推荐先用这个验证）

```bash
# 用 ticker 分析
python cli.py analyze AAPL

# 用中文公司名分析
python cli.py analyze 英伟达

# 测试模式：强制简体中文 + 常识性、非情景化的回答口径（等价于设置 ATLAS_FORCE_RESPONSE_LOCALE=zh）
python cli.py analyze --zh AAPL
python cli.py chat --zh "市盈率一般怎么理解？不要结合我个人情况分析。"

# 自由对话
python cli.py chat "分析一下苹果公司的基本面"

# 默认会在终端打印工具与 LangGraph 节点进度；不需要再加 --stream
# 若只要最终结果、不要进度行：
python cli.py analyze --quiet AAPL
python cli.py analyze -q --zh AAPL
python cli.py chat -q "看看美股强势股"
```

CLI 直接调用 LangGraph，不需要 FastAPI 或 OpenClaw。输出包含：
- Markdown 格式的情报简报
- JSON 结构化数据（`FundamentalReport`）
- 数据质量警告（如有）

**说明**：`make test` 里的 `tests/test_response_policy.py` 只校验「配置 + 提示词拼接」是否带上常识边界与 `zh` 约束，**不调用 LLM**，不能替代你在 CLI 上看的真实中文与语气；**日常集成验收请以本节 CLI 为准**。

### 基本面 RAG（可选，财报 / 深度文档）

默认关闭。在 `.env` 中设置 **`RAG_FUNDAMENTAL_ENABLED=true`**，并配置 **`EMBEDDING_API_KEY`**（及可选 **`EMBEDDING_BASE_URL`** / **`EMBEDDING_MODEL`**），数据目录默认 **`data/chroma/`**。启用后：通过 **`POST /api/v1/fundamental-documents`**（或 **`POST /api/v1/analyze`** 的 **`deep_document_text`**）将 **10-K、年报、MD&A 等纯文本** 按会话与标的写入 **Chroma**；分析时在 **`gather_data` 之前**检索相关片段，注入基本面子 Agent 与最终合成（与工具数据冲突时以工具为准）。详见 [docs/LANGCHAIN_WORKFLOW.md](docs/LANGCHAIN_WORKFLOW.md)。

### SSE 进度（HTTP API）

`/api/v1/chat` 与 `/api/v1/analyze` 请求体中设置 **`"stream": true`** 时，返回 **Server-Sent Events**（`text/event-stream`），事件类型包括：

- `token`：模型输出分片（若底层模型支持流式）
- `tool_start` / `tool_end`：子 Agent 工具调用起止

响应头含 `X-Session-Id`。OpenClaw 等客户端若需要「边生成边展示」，应使用 `stream: true` 并解析 SSE；默认 `stream: false` 为一次性 JSON。

### 4. 启动 API 服务

```bash
# 开发模式（热重载）
make dev

# 或直接运行
uvicorn app.main:app --reload --port 8000
```

### 5. 运行自动化测试（可选）

```bash
make test
```

主要用于 CI / 重构防回归；**与 CLI 手测互补**，不替代 `cli.py analyze --zh` 等端到端验证。

## 分析输出示例

### 结构化 JSON（`FundamentalReport`）

```json
{
  "ticker": "NVDA",
  "company_name": "NVIDIA Corporation",
  "industry": "Semiconductors",
  "current_price": 135.0,
  "profitability": {"gross_margin": 0.73, "roe": 1.15, "summary": "..."},
  "growth": {"revenue_growth_yoy": 1.22, "summary": "..."},
  "valuation": {"pe_ratio": 65.0, "ev_to_ebitda": 50.0, "summary": "..."},
  "financial_health": {"debt_to_equity": 0.41, "current_ratio": 4.17, "summary": "..."},
  "news_sentiment": {"overall": "positive", "summary": "..."},
  "intelligence_overview": {"summary": "Factual cross-cutting summary; no buy/sell/hold unless user asked."},
  "risk_factors": ["High valuation", "..."],
  "highlights": ["AI leadership", "..."]
}
```

### Markdown 报告

系统自动将结构化数据渲染为包含表格的 Markdown 报告，覆盖：
- 盈利分析（Gross Margin / Operating Margin / ROE / ROA）
- 增长分析（Revenue Growth / Earnings Growth）
- 估值分析（P/E / P/B / EV/EBITDA / PEG）
- 财务健康（Debt/Equity / Current Ratio / Free Cash Flow）
- 新闻情绪（Overall sentiment + key headlines）
- 同业对比（vs 3-5 家同行业公司）
- 事实摘要（Factual summary）+ 风险因素（数据向、非操作建议）

## API 文档

启动服务后访问 `http://localhost:8000/docs` 查看 Swagger 文档。

### 核心端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/analyze` | POST | 单股基本面分析（返回 JSON + Markdown，支持 SSE） |
| `/api/v1/chat` | POST | 自由对话（Agent 自动路由，支持 SSE） |
| `/api/v1/strong-stocks` | POST | 获取强势股监控池列表（筛选结果，非投资建议） |
| `/api/v1/watchlist` | POST/PUT | 添加/更新观察组 |
| `/api/v1/watchlist/{user_id}` | GET | 获取用户观察组 |
| `/api/v1/watchlist/{user_id}/{ticker}` | DELETE | 移除观察组中的股票 |
| `/api/v1/fundamental-documents` | POST | 上传深度文档（10-K 等）写入 RAG 向量库 |
| `/api/v1/health` | GET | 健康检查（含 LLM/monitor/RAG 状态） |
| `/api/v1/sessions/{id}` | GET | 获取会话历史 |

### `/api/v1/analyze` 请求/响应

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL"}'
```

响应：

```json
{
  "ticker": "AAPL",
  "session_id": "abc123",
  "report": "# Apple Inc. (AAPL) Fundamental Analysis\n...",
  "structured": { "...FundamentalReport JSON..." },
  "errors": [],
  "usage": {"total_calls": 5, "total_tokens": 3200},
  "timestamp": "2026-04-01T23:00:00"
}
```

### SSE 流式响应

将 `"stream": true` 传入 `/chat` 或 `/analyze`：

```
data: {"type": "tool_start", "tool": "get_company_profile"}
data: {"type": "tool_end", "tool": "get_company_profile"}
data: {"type": "token", "content": "Apple"}
data: [DONE]
```

## LangGraph 节点流程（17 节点）

```
START
  → parse_input         正则快速路径 + LLM fallback 意图分类 + ticker 提取
  ┌── single_stock/compare 路径 ──────────────────────────────────────┐
  │ → resolve_symbol    公司名→标准 ticker + yfinance 验证             │
  │ → [human_confirm]   歧义 ticker 暂停等待用户选择（interrupt 节点）   │
  │ → retrieve_rag      Adaptive RAG：Chroma 向量检索深度文档           │
  │ → gather_data ─┐    ReAct Agent 并行调用 8 个基本面工具             │
  │ → sentiment   ─┘    ReAct Agent 获取新闻 + 评估情绪                │
  │ → synthesis         LLM 生成 FundamentalReport JSON + Markdown     │
  │ → validate_result   检查 6 维度覆盖度，标注数据缺口                  │
  │ → reflect           LLM-as-Judge 评分，低分（<7）自动修订一次        │
  │ → render_output     结构化报告→固定模板 Markdown → END              │
  ├── strong_stocks 路径 ────────────────────────────────────────────┤
  │ → strong_stocks → retrieve_rag → synthesis → … → END             │
  ├── multi_step 路径（Dynamic Planning）────────────────────────────┤
  │ → plan → execute_step（循环）→ synthesis → … → END                │
  ├── update_config 路径 ────────────────────────────────────────────┤
  │ → update_config → END                                            │
  └── chat 路径 ─────────────────────────────────────────────────────┘
    → chat → END

辅助节点: supervisor（多 Agent 委派）、watchlist_add（观察组管理）
```

## 工具清单（13 个）

| 工具 | 文件 | 数据来源 | 说明 |
|------|------|----------|------|
| `get_company_profile` | `tools/company_profile.py` | Provider / OpenBB / yfinance | 公司概况、行业、市值 |
| `get_financial_statements` | `tools/financial_statements.py` | Provider / OpenBB / yfinance | 利润表 / 资产负债表 / 现金流 |
| `get_key_metrics` | `tools/key_metrics.py` | Provider / OpenBB / yfinance | PE/PB/ROE/负债率等指标 |
| `get_peer_comparison` | `tools/peer_comparison.py` | yfinance + 行业映射 | 同行业 3-5 家公司对比（含港股） |
| `get_risk_metrics` | `tools/risk_metrics.py` | yfinance | Beta/波动率/做空比例/内部人交易 |
| `get_catalysts` | `tools/catalysts.py` | yfinance | 下次财报日期/催化剂事件 |
| `get_company_news` | `tools/news_sentiment.py` | Provider / OpenBB / yfinance | 近期新闻 + 快照保底 |
| `get_price_history` | `tools/price_history.py` | yfinance | OHLCV 历史 K 线数据 |
| `get_technical_analysis` | `tools/technical_analysis.py` | yfinance + monitor/ | RSI/MACD/布林带/缩量突破 |
| `get_strong_stocks` | `tools/strong_stocks.py` | monitor/ 模块 + 快照 | 强势股监控池列表 |
| `get_market_overview` | `tools/market_data.py` | monitor/ + yfinance + 快照 | 大盘环境 + 指数快照 |
| `get_watchlist` | `tools/watchlist.py` | SQLite 本地 | 用户观察组管理 |
| `get_monitoring_alerts` | `tools/monitoring_alerts.py` | monitor/ 模块 | 缩量/突破告警扫描 |

## OpenClaw 对接

OpenClaw 侧只需 HTTP 调用以下端点：

```yaml
tools:
  - name: atlas_analyze
    endpoint: http://localhost:8000/api/v1/analyze
    method: POST
    parameters:
      ticker: { type: string, required: true }

  - name: atlas_chat
    endpoint: http://localhost:8000/api/v1/chat
    method: POST
    parameters:
      message: { type: string, required: true }

  - name: atlas_strong_stocks
    endpoint: http://localhost:8000/api/v1/strong-stocks
    method: POST
    parameters:
      market_type: { type: string, enum: [us_stock, etf, hk_stock] }
```

## 项目结构

```
Atlas/
├── langchain_agent/                # 后端核心
│   ├── cli.py                      # 本地 CLI 测试入口
│   ├── pyproject.toml              # 项目元数据与依赖
│   ├── .env                        # 环境变量（不提交 git）
│   ├── env.template                # 环境变量模板
│   ├── Makefile                    # 常用命令
│   ├── scripts/
│   │   └── warm_demo.py            # Demo 数据预热脚本
│   ├── cache/
│   │   └── snapshots/              # JSON 快照文件（warm_demo 生成）
│   ├── app/
│   │   ├── main.py                 # FastAPI 入口 + CORS + 异常处理
│   │   ├── config.py               # 统一配置（LLM/Provider/RAG/路径）
│   │   ├── dependencies.py         # 依赖注入
│   │   ├── api/
│   │   │   ├── routes.py           # API 路由（chat/analyze/strong-stocks/watchlist）
│   │   │   ├── schemas.py          # 请求/响应 Pydantic 模型
│   │   │   └── auth.py             # 认证中间件
│   │   ├── models/
│   │   │   ├── financial.py        # 财务数据模型
│   │   │   ├── analysis.py         # FundamentalReport 结构化模型
│   │   │   └── state.py            # AgentState（含 plan/reflection/delegation 字段）
│   │   ├── llm/
│   │   │   └── factory.py          # LLM 工厂（MiniMax/DeepSeek/Zhipu 三切换）
│   │   ├── providers/
│   │   │   ├── base.py             # FinancialDataProvider 抽象基类
│   │   │   ├── registry.py         # Provider 工厂（按配置选择）
│   │   │   ├── yfinance_provider.py
│   │   │   ├── openbb_provider.py
│   │   │   ├── fmp_provider.py     # Financial Modeling Prep API
│   │   │   ├── mock_provider.py    # 固定测试数据（AAPL/NVDA/AMD）
│   │   │   ├── ticker_cache.py     # yfinance TTL 缓存 + 快照 fallback
│   │   │   └── market_cache.py     # SQLite 市场快照/强势股缓存
│   │   ├── tools/                  # 13 个 LangChain 工具
│   │   ├── agents/
│   │   │   ├── graph.py            # LangGraph 主图（17 节点 + 条件边）
│   │   │   ├── nodes.py            # 所有节点实现（含 reflect/plan/supervisor）
│   │   │   ├── fundamental.py      # 基本面 ReAct Agent
│   │   │   ├── sentiment.py        # 情绪分析 Agent
│   │   │   └── synthesis.py        # 综合研判（JSON 提取 + 容错）
│   │   ├── prompts/                # Prompt 模板 + response_policy
│   │   ├── memory/
│   │   │   ├── store.py            # AsyncSqliteSaver 会话持久化
│   │   │   ├── watchlist.py        # SQLite 观察组表
│   │   │   ├── vector_store.py     # Chroma 向量存储（RAG）
│   │   │   └── embeddings.py       # Embedding 工厂
│   │   └── callbacks/              # CostTracker + StepLogger
│   ├── tests/                      # 14 个单元测试
│   └── eval/                       # 评估管线
│       ├── datasets/               # Golden dataset（意图分类样本）
│       ├── test_intent_accuracy.py # 意图分类准确率测试
│       ├── test_report_structure.py# 报告结构校验
│       ├── test_llm_judge.py       # LLM-as-Judge 评分测试
│       └── test_new_features.py    # 新特性路由/状态字段测试
├── frontend/                       # Next.js 前端
│   ├── app/                        # 页面（chat / watchlist / subscription）
│   ├── components/                 # UI 组件（analysis / candidates / chat / layout）
│   ├── lib/api.ts                  # 后端 API 客户端（REST + SSE 流式）
│   ├── next.config.mjs             # API 代理配置
│   └── package.json
└── monitor/                        # 强势股筛选/技术分析模块（sibling）
```

## 技术栈

| 组件 | 技术 |
|------|------|
| Agent 框架 | LangChain + LangGraph（17 节点状态机） |
| LLM | MiniMax M2.7（默认）/ DeepSeek V3 / 智谱 GLM |
| 金融数据 | yfinance + OpenBB + FMP + 本地快照 fallback |
| 后端框架 | FastAPI + uvicorn + SSE 流式 |
| 前端 | Next.js 14 + TailwindCSS + Framer Motion |
| 数据模型 | Pydantic v2 |
| 持久化 | SQLite（会话/观察组/市场缓存）+ Chroma（RAG 向量） |
| 可观测性 | CostTracker + StepLogger + LangSmith（可选） |
| 测试 | pytest + pytest-asyncio（14 单测 + 4 评估） |
| 部署 | Cloudflare Tunnel（后端）+ Next.js dev / Vercel（前端） |

## Demo 部署

### 数据预热

```bash
cd langchain_agent
python scripts/warm_demo.py           # 预热全部 demo 股票（AAPL/NVDA/TSLA/MSFT/GOOGL/AMD/META/0700.HK）
python scripts/warm_demo.py AAPL TSLA # 只预热指定股票
```

生成 `cache/snapshots/*.json` 快照文件，当 yfinance API 受限时自动降级使用。

### 本地启动

```bash
# 终端 1: 后端
cd langchain_agent
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 终端 2: 前端
cd frontend
npx next dev --port 3000
```

### 远程访问（Cloudflare Tunnel）

```powershell
# 终端 3: 后端 Tunnel
cloudflared tunnel --url http://localhost:8000
# → 获得 https://xxx.trycloudflare.com（后端 URL）

# 终端 2: 重启前端，设置后端 Tunnel URL
$env:NEXT_PUBLIC_API_DIRECT="https://xxx.trycloudflare.com/api/v1"
npx next dev --port 3000

# 终端 4: 前端 Tunnel
cloudflared tunnel --url http://localhost:3000
# → 获得 https://yyy.trycloudflare.com → 发给 HR 打开
```

## 职责边界

| 模块 | 负责方 |
|------|--------|
| 基本面分析（本项目） | LangChain Agent |
| 客户端交互 / TG Bot | OpenClaw |
| 监控参数修改 | OpenClaw |
| 强势股列表展示 | OpenClaw（调用本项目 API） |
| "看第 2 只基本面" | OpenClaw 维护列表，调用 `/analyze` |
