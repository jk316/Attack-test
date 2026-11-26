"""Render a lesson document (``lessons/{run_id}.md``) from run stats + narrative."""

from __future__ import annotations

from typing import Any

from src.lessons.records import Run
from src.lessons.stats import RunStats


def _fmt(value: Any) -> str:
    return "-" if value is None else str(value)


def _best_label(stats: RunStats) -> str:
    if stats.best is None:
        return "无（所有轮次均无有效观测）"
    iteration = stats.best.iteration
    prefix = f"第 {iteration} 轮" if isinstance(iteration, int) else "某轮"
    return f"{prefix}（{stats.best.tool}，得分 {stats.best_score:.1f}）"


def render_lesson(
    run_id: str,
    run: Run,
    stats: RunStats,
    narrative: tuple[str, str],
    used_llm: bool,
) -> str:
    """Render the full lesson Markdown document."""
    lessons_text, suggestions_text = narrative
    generation = "LLM 叙事" if used_llm else "规则要点"

    lines: list[str] = [
        f"# 经验教训 · {run_id}",
        "",
        (f"> 目标: {run.target_ip or '未知'} ｜ 轮数: {run.iterations} "
         f"｜ 时间: {run.start_ts or '-'} ~ {run.end_ts or '-'} (UTC) "
         f"｜ 生成: {generation}"),
        "",
        "## 观测概览",
        "",
        "| 轮次 | 工具 | 目标 | 关键参数 | RTT(ms) | 丢包% | HTTP成功率 | HTTP TTFB | 备注 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for obs in stats.observations:
        note = "" if obs.has_observation else "无观测"
        lines.append(
            f"| {_fmt(obs.iteration)} | {obs.tool} | {_fmt(obs.target_ip)} "
            f"| {obs.key_params} | {_fmt(obs.rtt)} | {_fmt(obs.loss)} "
            f"| {_fmt(obs.http_success_rate)} | {_fmt(obs.http_ttfb_ms)} | {note} |"
        )

    lines += [
        "",
        "## 关键结论",
        "",
        f"- 最佳一轮: {_best_label(stats)}",
        f"- 趋势: {stats.trend}",
        f"- 收敛: {stats.converged}（启发式）",
        "",
        "## 经验教训",
        "",
        lessons_text,
        "",
        "## 下次实验建议",
        "",
        suggestions_text,
        "",
    ]
    return "\n".join(lines)


def render_rule_lessons(stats: RunStats) -> tuple[str, str]:
    """Deterministic rule-derived lessons/suggestions (LLM fallback)."""
    if stats.best is not None:
        b = stats.best
        lessons = (
            f"- 最佳一轮为第 {b.iteration} 轮（工具 {b.tool}）："
            f"RTT={_fmt(b.rtt)}ms、丢包={_fmt(b.loss)}%、"
            f"HTTP成功率={_fmt(b.http_success_rate)}、TTFB={_fmt(b.http_ttfb_ms)}ms，"
            "该参数组合效果最强。\n"
        )
    else:
        lessons = "- 所有轮次均无有效观测，无法判定哪种参数最有效；需先补齐观测手段。\n"

    tools = "、".join(f"{name}×{count}" for name, count in sorted(stats.tool_counts.items())) or "无"
    lessons += f"- 工具分布: {tools}。\n"
    lessons += f"- RTT 趋势: {stats.trend}；收敛判定: {stats.converged}（启发式）。"

    suggestions = (
        "- 沿用最佳一轮的参数组合，并在此基础上加大 pps/rate 继续试探上限。\n"
        "- 对无观测的轮次，先确保后台监控（ping/HTTP）在攻击窗口内有采样，再据此决策。"
    )
    return lessons, suggestions
