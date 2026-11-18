"""Regression tests for the DeepSeek reasoning_content monkey-patch (G4 / FR-009 / SC-002).

Importing src.agent.graph applies _patch_reasoning_content() (module-level
side effect, mirrors production). These tests drive the patched
langchain_openai conversion functions directly through ≥3 assistant-message
round-trips and assert reasoning_content survives both inbound extraction
(dict → AIMessage) and outbound echo (AIMessage → request dict). No LLM or
network calls.
"""
import pytest

# Import applies the patch (same path as production: graph.py top level).
from src.agent.graph import _patch_reasoning_content  # noqa: F401
import langchain_openai.chat_models.base as base  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

THINKING_1 = "第一轮推理：目标基线 12ms，尝试 UDP 低速率。"
THINKING_2 = "第二轮推理：loss 上升，加大 pps。"
THINKING_3 = "第三轮推理：RTT 回落，切换 TCP SYN。"


class TestInboundExtraction:
    def test_reasoning_content_extracted_into_additional_kwargs(self):
        msg = base._convert_dict_to_message(
            {"role": "assistant", "content": "继续", "reasoning_content": THINKING_1}
        )
        assert isinstance(msg, AIMessage)
        assert msg.additional_kwargs.get("reasoning_content") == THINKING_1

    def test_dict_without_reasoning_content_is_untouched(self):
        msg = base._convert_dict_to_message(
            {"role": "assistant", "content": "无推理内容"}
        )
        assert isinstance(msg, AIMessage)
        assert "reasoning_content" not in msg.additional_kwargs


class TestOutboundEcho:
    def test_reasoning_content_echoed_back_in_request_dict(self):
        msg = AIMessage(
            content="结论",
            additional_kwargs={"reasoning_content": THINKING_2},
        )
        d = base._convert_message_to_dict(msg)
        assert d.get("reasoning_content") == THINKING_2

    def test_message_without_reasoning_content_omits_key(self):
        d = base._convert_message_to_dict(AIMessage(content="无推理"))
        assert "reasoning_content" not in d


class TestMultiRoundRoundTrip:
    """≥3 轮 AIMessage 往返：入站提取与出站回传均不丢失（SC-002）。"""

    def test_three_round_round_trip_preserves_each_round(self):
        for thinking in (THINKING_1, THINKING_2, THINKING_3):
            # round N inbound: API dict → AIMessage
            msg = base._convert_dict_to_message(
                {"role": "assistant", "content": f"第 N 轮", "reasoning_content": thinking}
            )
            assert msg.additional_kwargs.get("reasoning_content") == thinking
            # round N+1 outbound: AIMessage → API dict（必须原样回传）
            d = base._convert_message_to_dict(msg)
            assert d.get("reasoning_content") == thinking
            # 下一轮入站再解析，链条继续
            msg2 = base._convert_dict_to_message(d)
            assert msg2.additional_kwargs.get("reasoning_content") == thinking

    def test_three_round_alternating_content_no_cross_contamination(self):
        history = [THINKING_1, THINKING_2, THINKING_3]
        carried = None
        for thinking in history:
            msg = base._convert_dict_to_message(
                {"role": "assistant", "content": "…", "reasoning_content": thinking}
            )
            d = base._convert_message_to_dict(msg)
            carried = d.get("reasoning_content")
            assert carried == thinking  # 每一轮都精确等于本轮推理内容
        assert carried == THINKING_3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
