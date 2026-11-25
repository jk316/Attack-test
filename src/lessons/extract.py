"""LLM narrative layer: turn run stats (+ optional agent-log segment) into
semantic "经验教训 / 下次实验建议" text. Degrades to deterministic rule
lessons when the LLM is unavailable (spec 010 FR-004).
"""

from __future__ import annotations

import logging
import os

from src.lessons.render import render_rule_lessons
from src.lessons.stats import RunStats
from src.llm.client import LLMClient, LLMClientError

logger = logging.getLogger("lessons")

_SECTION_MARKER = "下次实验建议"
_SEGMENT_MAX_CHARS = 8000


def llm_client_from_env() -> LLMClient | None:
    """Build an :class:`LLMClient` from env; ``None`` when no key is set."""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        return None
    try:
        return LLMClient()
    except LLMClientError:
        return None


def _split_narrative(text: str, marker: str = _SECTION_MARKER) -> tuple[str, str]:
    """Split LLM output into (lessons, suggestions) on the section marker."""
    idx = text.find(marker)
    if idx < 0:
        return text.strip(), ""
    lessons = text[:idx].strip()
    suggestions = text[idx + len(marker):].strip().lstrip(":：\n").strip()
    return lessons, suggestions


def _build_prompt(stats: RunStats, segment_text: str | None) -> str:
    parts = [
        "你是网络攻击实验复盘助手，请基于以下实测观测数据提炼经验教训与下次实验建议。",
        "",
        "观测数据（每轮）：",
    ]
    for obs in stats.observations:
        parts.append(
            f"- 第{obs.iteration}轮 {obs.tool}: RTT={obs.rtt}ms, 丢包={obs.loss}%, "
            f"HTTP成功率={obs.http_success_rate}, TTFB={obs.http_ttfb_ms}ms, "
            f"参数={obs.key_params or '无'}"
        )
    if stats.best is not None:
        parts.append(f"最佳一轮: 第{stats.best.iteration}轮（{stats.best.tool}）")
    parts.append(f"RTT 趋势: {stats.trend}；收敛: {stats.converged}")

    if segment_text:
        segment = segment_text
        if len(segment) > _SEGMENT_MAX_CHARS:
            segment = segment[:_SEGMENT_MAX_CHARS] + "\n…（截断）"
        parts += ["", "Agent 复盘对话片段：", segment]

    parts += [
        "",
        "请输出两段：第一段以「经验教训」开头，第二段以「下次实验建议」开头，"
        "每段用简洁中文要点（每点一行）。",
    ]
    return "\n".join(parts)


def build_narrative(
    stats: RunStats,
    segment_text: str | None,
    client: LLMClient | None,
) -> tuple[str, str, bool]:
    """Return ``(lessons_text, suggestions_text, used_llm)``.

    ``used_llm`` is ``False`` when ``client`` is ``None`` or the call fails —
    the returned text is then the deterministic rule fallback (never empty).
    """
    if client is None:
        lessons, suggestions = render_rule_lessons(stats)
        return lessons, suggestions, False

    prompt = _build_prompt(stats, segment_text)
    try:
        text = client.chat_text([
            {
                "role": "system",
                "content": "你是网络攻击实验复盘助手，只依据给定数据作答。",
            },
            {"role": "user", "content": prompt},
        ])
        lessons, suggestions = _split_narrative(text)
        return lessons, suggestions, True
    except Exception as exc:  # noqa: BLE001 — deliberate degradation boundary
        logger.warning("LLM narrative failed, falling back to rule lessons: %s", exc)
        lessons, suggestions = render_rule_lessons(stats)
        return lessons, suggestions, False
