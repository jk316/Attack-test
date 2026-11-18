"""Unit tests for src/main.py::VerboseCallback (G8 / FR-013).

INFO level emits structured [LLM INPUT]/[LLM OUTPUT] lines with tool-call
names and truncated previews (MSG_PREVIEW_LEN + "… (+N chars)" annotation);
DEBUG level carries full untruncated content. No LLM or I/O — the callback is
fed synthetic messages and log records are captured with caplog.
"""
import logging
from types import SimpleNamespace

import pytest

from src.main import VerboseCallback, MSG_PREVIEW_LEN


def _make_msg(content: str, tool_calls=None, extra=None, msg_type="ai"):
    return SimpleNamespace(
        type=msg_type,
        content=content,
        tool_calls=tool_calls or [],
        additional_kwargs=extra or {},
    )


@pytest.fixture
def cb():
    return VerboseCallback()


class TestChatModelStart:
    def test_info_line_reports_structure(self, cb, caplog):
        caplog.set_level(logging.INFO, logger="agent")
        msgs = [_make_msg("你好"), _make_msg("这是模型回复")]
        cb.on_chat_model_start(None, [msgs])
        assert any("[LLM INPUT] 总消息: 2, 本轮新增: 2" in r.message
                   for r in caplog.records)
        assert any("[0] ai: 你好" in r.message for r in caplog.records)

    def test_info_line_names_tool_calls(self, cb, caplog):
        caplog.set_level(logging.INFO, logger="agent")
        msgs = [_make_msg("", tool_calls=[{"name": "traffic_send", "args": {}}])]
        cb.on_chat_model_start(None, [msgs])
        assert any("tool_calls=['traffic_send']" in r.message
                   for r in caplog.records)

    def test_long_content_truncated_with_annotation(self, cb, caplog):
        caplog.set_level(logging.INFO, logger="agent")
        long_text = "长" * (MSG_PREVIEW_LEN + 100)
        cb.on_chat_model_start(None, [[_make_msg(long_text)]])
        info_lines = [r.message for r in caplog.records if r.levelno == logging.INFO]
        preview_line = next(line for line in info_lines if "[0]" in line)
        assert "… (+100 chars" in preview_line
        assert "长" * MSG_PREVIEW_LEN in preview_line
        assert "长" * (MSG_PREVIEW_LEN + 100) not in preview_line

    def test_debug_level_has_full_content(self, cb, caplog):
        caplog.set_level(logging.DEBUG, logger="agent")
        long_text = "全量" * (MSG_PREVIEW_LEN + 50)
        cb.on_chat_model_start(None, [[_make_msg(long_text)]])
        debug_lines = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any(long_text in line for line in debug_lines)

    def test_additional_kwargs_logged_at_debug(self, cb, caplog):
        caplog.set_level(logging.DEBUG, logger="agent")
        msg = _make_msg("x", extra={"reasoning_content": "内部推理"})
        cb.on_chat_model_start(None, [[msg]])
        debug_lines = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("reasoning_content" in line for line in debug_lines)

    def test_incremental_window_tracks_new_messages(self, cb, caplog):
        caplog.set_level(logging.INFO, logger="agent")
        cb.on_chat_model_start(None, [[_make_msg("第一轮")]])
        cb.on_chat_model_start(None, [[_make_msg("第一轮"), _make_msg("第二轮")]])
        assert any("总消息: 2, 本轮新增: 1" in r.message
                   for r in caplog.records)


class TestChatModelEnd:
    def _response(self, msg):
        return SimpleNamespace(generations=[[SimpleNamespace(message=msg)]])

    def test_info_line_reports_tool_calls(self, cb, caplog):
        caplog.set_level(logging.INFO, logger="agent")
        msg = _make_msg("", tool_calls=[{"name": "ping_rtt", "args": {"count": 4}}])
        cb.on_chat_model_end(self._response(msg))
        assert any("[LLM OUTPUT] tool_calls=['ping_rtt']" in r.message
                   for r in caplog.records)

    def test_debug_level_has_content_and_args(self, cb, caplog):
        caplog.set_level(logging.DEBUG, logger="agent")
        msg = _make_msg(
            "总结", tool_calls=[{"name": "traffic_send", "args": {"pps": 500}}],
        )
        cb.on_chat_model_end(self._response(msg))
        debug_lines = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("args:" in line and '"pps"' in line for line in debug_lines)
        assert any("content: 总结" in line for line in debug_lines)

    def test_output_content_truncated_at_debug(self, cb, caplog):
        caplog.set_level(logging.DEBUG, logger="agent")
        long_text = "出" * (MSG_PREVIEW_LEN + 30)
        cb.on_chat_model_end(self._response(_make_msg(long_text)))
        assert not any(long_text in r.message for r in caplog.records)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
