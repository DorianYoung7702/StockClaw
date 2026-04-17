"""Shared response policy: commonsense-only, no personalised scenario interpretation.

Used to augment system prompts for fundamental / sentiment / synthesis / chat.
"""

from __future__ import annotations

COMMONSENSE_SCENARIO_RULES = """\
### 具体情况与回答边界（情报 / 常识）
- 用户描述个人处境、账户、仓位、期限或问「我该怎么办」时：只提供**一般性、常识性**信息（公开概念、常见分析维度、教材级框架），**不对该用户的具体情景做针对性解读或结论**。
- 不要臆测用户的资金、持仓、风险偏好、真实目标；避免「对你来说」「结合你的情况」「建议你此时」等指向个人的表述。
- 若问题隐含个人决策或明确索要「买哪只」「怎么配」：先用一两句说明**无法根据其自述情况做判断**，只提供**非个人化**的常识或教育性信息（例如风险类型、信息渠道、需自行决策），**不结合其资金量、期限、家庭状况等做具体标的或仓位解读**。
- 默认与用户的提问语言一致；下列「输出语言」约束若启用则优先生效。"""

LOCALE_ZH_FORCE = """\
### 输出语言（测试 / 演示模式）
- **无论用户输入何种语言，所有面向用户的可见输出一律使用简体中文**（含分析正文、列表、表格说明；工具调用旁白如需输出给用户也用中文）。
- 若需输出结构化 JSON，其中所有给人读的字符串字段（summary、highlights、risk_factors 等）也须为简体中文。"""


def augment_system_prompt(base_instruction: str) -> str:
    """Append global intelligence policy and optional locale override to a system prompt."""
    from app.config import get_settings

    settings = get_settings()
    parts = [base_instruction.rstrip(), "", COMMONSENSE_SCENARIO_RULES]
    if settings.atlas_force_response_locale == "zh":
        parts.extend(["", LOCALE_ZH_FORCE])
    return "\n".join(parts)
