"""Tests for src/lessons/render.py — Markdown lesson rendering."""

from src.lessons.records import Run
from src.lessons.render import render_lesson, render_rule_lessons
from src.lessons.stats import summarize_run


def _run(rows):
    return Run(
        run_id="20261125T070649-9e1fe6",
        rows=tuple(rows),
        target_ip="10.0.0.1",
        start_ts="2026-11-25T07:06:50+00:00",
        end_ts="2026-11-25T07:06:52+00:00",
    )


def test_render_contains_sections():
    rows = [{
        "iteration": 1, "tool": "traffic_send",
        "params": {"target_ip": "10.0.0.1", "pps": 100},
        "rtt": 1.2, "loss": 0.0,
    }]
    run = _run(rows)
    stats = summarize_run(rows)

    doc = render_lesson(run.run_id, run, stats, ("教训", "建议"), used_llm=False)

    assert "# 经验教训 · 20261125T070649-9e1fe6" in doc
    assert "生成: 规则要点" in doc
    for section in ("## 观测概览", "## 关键结论", "## 经验教训", "## 下次实验建议"):
        assert section in doc
    assert "10.0.0.1" in doc
    assert "教训" in doc
    assert "建议" in doc


def test_render_no_observation_note():
    rows = [{"iteration": 1, "tool": "traffic_send", "params": {}}]
    run = _run(rows)
    stats = summarize_run(rows)

    doc = render_lesson(run.run_id, run, stats, ("教训", "建议"), used_llm=True)

    assert "无观测" in doc
    assert "生成: LLM 叙事" in doc


def test_render_best_none_when_no_observation():
    rows = [{"iteration": 1, "tool": "traffic_send", "params": {}}]
    run = _run(rows)
    stats = summarize_run(rows)

    doc = render_lesson(run.run_id, run, stats, ("教训", "建议"), used_llm=False)

    assert "最佳一轮: 无" in doc


def test_rule_lessons():
    rows = [{
        "iteration": 1, "tool": "traffic_send",
        "params": {"target_ip": "10.0.0.1"}, "rtt": 5.0,
    }]
    stats = summarize_run(rows)

    lessons, suggestions = render_rule_lessons(stats)

    assert "最佳一轮" in lessons
    assert suggestions
