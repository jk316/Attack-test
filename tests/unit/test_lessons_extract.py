"""Tests for src/lessons/extract.py — LLM narrative + rule fallback."""

from src.lessons.extract import (
    build_narrative,
    llm_client_from_env,
    _split_narrative,
)
from src.lessons.stats import summarize_run


class _FakeClient:
    def __init__(self, text=None, fail=False):
        self.text = text or "经验教训：\n- 有效。\n下次实验建议：\n- 加大。\n"
        self.fail = fail
        self.calls = []

    def chat_text(self, messages):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("boom")
        return self.text


def _stats():
    return summarize_run([{
        "iteration": 1, "tool": "traffic_send",
        "params": {"target_ip": "10.0.0.1"}, "rtt": 5.0,
    }])


def test_build_narrative_uses_llm():
    client = _FakeClient()
    lessons, suggestions, used = build_narrative(_stats(), None, client)

    assert used is True
    assert "有效" in lessons
    assert "加大" in suggestions
    assert len(client.calls) == 1


def test_build_narrative_fallback_on_error():
    client = _FakeClient(fail=True)
    lessons, suggestions, used = build_narrative(_stats(), None, client)

    assert used is False
    assert "最佳一轮" in lessons  # rule fallback content
    assert suggestions


def test_build_narrative_no_client():
    lessons, suggestions, used = build_narrative(_stats(), None, None)

    assert used is False
    assert "最佳一轮" in lessons
    assert suggestions


def test_llm_client_from_env_no_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert llm_client_from_env() is None


def test_split_narrative():
    lessons, suggestions = _split_narrative(
        "经验教训：\n- a\n下次实验建议：\n- b\n"
    )
    assert "a" in lessons
    assert "b" in suggestions
    assert "下次实验建议" not in suggestions


def test_split_narrative_missing_marker():
    lessons, suggestions = _split_narrative("只有一段\n- x\n")
    assert "x" in lessons
    assert suggestions == ""
