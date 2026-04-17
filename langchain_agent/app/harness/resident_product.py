from __future__ import annotations

import re
from typing import Any


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _get_metric(report: dict[str, Any], path: tuple[str, ...]) -> float | None:
    current: Any = report
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _to_float(current)


def _get_text(report: dict[str, Any], path: tuple[str, ...]) -> str:
    current: Any = report
    for key in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return current if isinstance(current, str) else ""


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    if abs(previous) < 1e-9:
        return None
    return (current - previous) / abs(previous)


def _format_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def _stance_priority(stance: str) -> int:
    order = {"warning": 4, "cautious": 3, "neutral": 2, "positive": 1}
    return order.get(stance, 0)


def _confidence_label(score: float) -> str:
    if score >= 0.78:
        return "高"
    if score >= 0.55:
        return "中"
    return "低"


def normalize_user_error(error_text: str) -> str:
    raw = str(error_text or "").strip()
    if not raw:
        return "分析过程中出现异常，本轮结果已降级处理"

    lowered = raw.lower()
    if "529" in lowered or "overloaded" in lowered or "负载较高" in raw:
        return "LLM 服务繁忙，本轮合成已降级，结论完整性受限"

    if "degraded: all data sources failed" in lowered:
        if "sentiment_node" in lowered:
            return "新闻/情绪数据源暂时不可用，本轮情绪判断不完整"
        return "部分外部数据源暂时不可用，本轮结论基于不完整数据"

    if "could not be verified" in lowered:
        return "标的代码校验未完全确认，部分外部数据可能缺失"

    if "所有指标均为空" in raw or "维度数据完全缺失" in raw:
        return "多个关键基本面维度缺失，本轮结论置信度下降"

    if "部分指标缺失" in raw:
        return "部分基本面指标缺失，本轮结论置信度下降"

    if "timeout" in lowered or "timed out" in lowered:
        return "分析超时，本轮结果不完整"

    if "connection" in lowered or "connect" in lowered:
        return "外部数据连接异常，本轮结果不完整"

    if raw.startswith("Error code:") or "request_id" in lowered:
        return "外部服务异常，本轮已降级输出"

    cleaned = re.sub(r"\s+", " ", raw)
    return cleaned[:120]


def dedupe_texts(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def derive_confidence(
    quality_score: float,
    *,
    errors: list[str] | None = None,
    drift_signals: list[dict[str, Any]] | None = None,
) -> tuple[float, str, list[str]]:
    score = 0.62
    reasons: list[str] = []
    errors = errors or []
    drift_signals = drift_signals or []

    if quality_score > 0:
        score += max(min((quality_score - 7.0) / 10.0, 0.25), -0.25)
        if quality_score < 7.0:
            reasons.append("本轮质量评分偏低")

    if errors:
        score -= min(len(errors) * 0.08, 0.24)
        reasons.append("存在数据缺失或恢复降级")

    for signal in drift_signals:
        severity = str(signal.get("severity", ""))
        action = str(signal.get("action", ""))
        if severity == "high":
            score -= 0.18
            reasons.append("近期存在高优先级漂移/失败")
        elif severity == "medium":
            score -= 0.1
            reasons.append(f"近期触发{action or '中等级漂移'}")
        elif severity == "low":
            score -= 0.04

    score = max(0.12, min(score, 0.95))
    return score, _confidence_label(score), reasons


def build_symbol_snapshot(
    ticker: str,
    report: dict[str, Any] | None,
    *,
    quality_score: float = 0.0,
    errors: list[str] | None = None,
    previous_snapshot: dict[str, Any] | None = None,
    drift_signals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    report = report or {}
    errors = errors or []
    previous_snapshot = previous_snapshot or {}
    drift_signals = drift_signals or []

    sentiment = _get_text(report, ("news_sentiment", "overall")) or "neutral"
    overview = _get_text(report, ("intelligence_overview", "summary"))
    highlights = list(report.get("highlights") or [])
    risks = list(report.get("risk_factors") or [])

    pe_ratio = _get_metric(report, ("valuation", "pe_ratio"))
    revenue_growth = _get_metric(report, ("growth", "revenue_growth_yoy"))
    earnings_growth = _get_metric(report, ("growth", "earnings_growth_yoy"))
    debt_to_equity = _get_metric(report, ("financial_health", "debt_to_equity"))

    stance = "neutral"
    stance_reasons: list[str] = []
    if sentiment == "negative" or (revenue_growth is not None and revenue_growth < -0.05):
        stance = "warning"
        stance_reasons.append("情绪或增长出现明显转弱")
    elif (pe_ratio is not None and pe_ratio >= 30 and (revenue_growth is None or revenue_growth < 0.08)) or (
        debt_to_equity is not None and debt_to_equity >= 2.0
    ):
        stance = "cautious"
        stance_reasons.append("估值/杠杆与增长匹配度偏弱")
    elif sentiment == "positive" and (
        (revenue_growth is not None and revenue_growth >= 0.1)
        or (earnings_growth is not None and earnings_growth >= 0.1)
    ):
        stance = "positive"
        stance_reasons.append("增长与情绪同时偏强")
    else:
        stance_reasons.append("基本面与情绪暂未形成强烈偏向")

    prev_metrics = previous_snapshot.get("metrics") if isinstance(previous_snapshot, dict) else {}
    prev_pe = _to_float((prev_metrics or {}).get("pe_ratio"))
    prev_rev = _to_float((prev_metrics or {}).get("revenue_growth_yoy"))
    prev_sentiment = str((prev_metrics or {}).get("sentiment_overall", ""))
    prev_risk_count = int((prev_metrics or {}).get("risk_count", 0) or 0)
    prev_stance = str(previous_snapshot.get("stance", "")) if isinstance(previous_snapshot, dict) else ""

    changes: list[str] = []
    change_severity = "none"

    pe_change = _pct_change(pe_ratio, prev_pe)
    if pe_change is not None and abs(pe_change) >= 0.2:
        change_severity = "major"
        changes.append(f"PE 从 {prev_pe:.1f}x 变到 {pe_ratio:.1f}x ({pe_change * 100:+.0f}%)")
    elif pe_change is not None and abs(pe_change) >= 0.1:
        change_severity = "moderate"
        changes.append(f"PE 小幅变化至 {pe_ratio:.1f}x")

    rev_change = None
    if revenue_growth is not None and prev_rev is not None:
        rev_change = revenue_growth - prev_rev
        if abs(rev_change) >= 0.05:
            change_severity = "major" if change_severity != "major" else change_severity
            changes.append(
                f"营收增速从 {_format_pct(prev_rev)} 变到 {_format_pct(revenue_growth)}"
            )
        elif abs(rev_change) >= 0.02 and change_severity == "none":
            change_severity = "moderate"
            changes.append(f"营收增速小幅变化至 {_format_pct(revenue_growth)}")

    if prev_sentiment and sentiment and prev_sentiment != sentiment:
        if change_severity == "none":
            change_severity = "moderate"
        changes.append(f"新闻情绪由 {prev_sentiment} 转为 {sentiment}")

    if prev_risk_count != len(risks):
        if abs(prev_risk_count - len(risks)) >= 2:
            change_severity = "major" if change_severity != "major" else change_severity
        elif change_severity == "none":
            change_severity = "moderate"
        changes.append(f"风险项数量由 {prev_risk_count} 项变为 {len(risks)} 项")

    if prev_stance and prev_stance != stance:
        change_severity = "major" if change_severity != "major" else change_severity
        changes.append(f"结论立场由 {prev_stance} 调整为 {stance}")

    if not changes:
        changes.append("与上轮相比暂无实质性变化")

    confidence_score, confidence_label, confidence_reasons = derive_confidence(
        quality_score,
        errors=errors,
        drift_signals=drift_signals,
    )

    update_mode = "stable"
    if change_severity == "major":
        update_mode = "full_refresh"
    elif change_severity == "moderate":
        update_mode = "incremental"

    key_reason = stance_reasons[0] if stance_reasons else ""
    if confidence_label == "低" and confidence_reasons:
        key_reason = f"{key_reason}；但{confidence_reasons[0]}"

    return {
        "ticker": ticker,
        "stance": stance,
        "change_severity": change_severity,
        "update_mode": update_mode,
        "conclusion": {
            "title": f"{ticker} — {stance}",
            "summary": overview or (highlights[0] if highlights else "暂无可用摘要"),
            "why": key_reason,
            "changes": changes,
            "top_risk": risks[0] if risks else "暂无显著新增风险",
            "top_catalyst": highlights[0] if highlights else "暂无显著催化",
            "confidence": confidence_label,
            "confidence_score": round(confidence_score, 2),
            "confidence_reasons": confidence_reasons,
        },
        "metrics": {
            "pe_ratio": pe_ratio,
            "revenue_growth_yoy": revenue_growth,
            "earnings_growth_yoy": earnings_growth,
            "debt_to_equity": debt_to_equity,
            "sentiment_overall": sentiment,
            "risk_count": len(risks),
            "quality_score": quality_score,
        },
        "highlights": highlights[:3],
        "risk_factors": risks[:3],
        "errors": errors,
    }


def build_watchlist_summary(
    symbols: list[dict[str, Any]],
    *,
    drift_signals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    drift_signals = drift_signals or []
    major_changes = [item for item in symbols if item.get("change_severity") == "major"]
    attention = [
        item for item in symbols
        if item.get("stance") in {"warning", "cautious"} or item.get("change_severity") == "major"
    ]
    stable = [item for item in symbols if item.get("change_severity") == "none"]

    overall_stance = "neutral"
    if any(item.get("stance") == "warning" for item in symbols):
        overall_stance = "warning"
    elif len([item for item in symbols if item.get("stance") == "cautious"]) >= 2:
        overall_stance = "cautious"
    elif any(item.get("stance") == "positive" for item in symbols) and not attention:
        overall_stance = "positive"

    confidence_values = [
        float(item.get("conclusion", {}).get("confidence_score", 0.0) or 0.0)
        for item in symbols
        if item.get("conclusion")
    ]
    avg_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
    confidence_label = _confidence_label(avg_confidence)

    watchlist_change = "本轮观察组整体较稳定"
    if major_changes:
        tickers = ", ".join(item.get("ticker", "") for item in major_changes[:3] if item.get("ticker"))
        watchlist_change = f"本轮有 {len(major_changes)} 只标的出现显著变化：{tickers}"
    elif attention:
        tickers = ", ".join(item.get("ticker", "") for item in attention[:3] if item.get("ticker"))
        watchlist_change = f"本轮重点关注仍集中在：{tickers}"

    summary_lines = [f"# 常驻观察组结论\n"]
    summary_lines.append(f"- 总体立场：{overall_stance}")
    summary_lines.append(f"- 变化判断：{watchlist_change}")
    summary_lines.append(f"- 置信度：{confidence_label} ({avg_confidence:.2f})")
    if stable:
        stable_tickers = ", ".join(item.get("ticker", "") for item in stable[:5] if item.get("ticker"))
        summary_lines.append(f"- 稳定标的：{stable_tickers or '暂无'}")
    if attention:
        summary_lines.append("\n## 需要关注")
        for item in attention[:5]:
            conclusion = item.get("conclusion", {})
            summary_lines.append(
                f"- {item.get('ticker', '')}: {conclusion.get('why', '')}；{(conclusion.get('changes') or [''])[0]}"
            )

    if drift_signals:
        summary_lines.append("\n## 系统自我校准")
        for signal in drift_signals[:3]:
            summary_lines.append(
                f"- 检测到 {signal.get('signal', '')}（{signal.get('severity', '')}），动作：{signal.get('action', '') or '观察中'}"
            )

    return {
        "overall_stance": overall_stance,
        "headline": watchlist_change,
        "confidence": confidence_label,
        "confidence_score": round(avg_confidence, 2),
        "symbols_requiring_attention": [item.get("ticker", "") for item in attention[:5] if item.get("ticker")],
        "stable_symbols": [item.get("ticker", "") for item in stable[:5] if item.get("ticker")],
        "major_change_count": len(major_changes),
        "drift_signals": drift_signals,
        "markdown": "\n".join(summary_lines).strip(),
    }


def build_symbol_context(previous_snapshot: dict[str, Any] | None, drift_signals: list[dict[str, Any]] | None = None) -> str:
    previous_snapshot = previous_snapshot or {}
    drift_signals = drift_signals or []
    if not previous_snapshot and not drift_signals:
        return ""

    parts: list[str] = []
    conclusion = previous_snapshot.get("conclusion") or {}
    metrics = previous_snapshot.get("metrics") or {}
    if previous_snapshot:
        parts.append("[上一轮观察结论]")
        parts.append(f"- 立场: {previous_snapshot.get('stance', 'neutral')}")
        if conclusion.get("why"):
            parts.append(f"- 原因: {conclusion['why']}")
        if metrics.get("pe_ratio") is not None:
            parts.append(f"- 上轮PE: {metrics['pe_ratio']}")
        if metrics.get("revenue_growth_yoy") is not None:
            parts.append(f"- 上轮营收增速: {metrics['revenue_growth_yoy']}")

    if drift_signals:
        parts.append("[本轮校准要求]")
        for signal in drift_signals[:3]:
            action = signal.get("action", "")
            signal_name = signal.get("signal", "")
            if action == "tighten_kpi_filters":
                parts.append(f"- 因{signal_name}，请重点补齐缺失维度并降低对弱证据的依赖")
            elif action == "re_anchor_task_spec":
                parts.append(f"- 因{signal_name}，请重新锚定结论，优先解释本轮变化而不是重复旧结论")
            else:
                parts.append(f"- 关注漂移信号: {signal_name} ({signal.get('severity', '')})")

    return "\n".join(parts)
