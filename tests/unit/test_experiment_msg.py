"""_msg_to_dict 基线单元测试（007-T003）。

锁定 backend/experiment.py 消息转换契约：role/content/tool_calls 字段，
tool_calls 为 [{name, args}] 列表，无工具调用时 tool_calls 为 None。
"""

from unittest.mock import MagicMock

from backend.experiment import _msg_to_dict


def _msg(msg_type: str, content: str, tool_calls=None):
    m = MagicMock()
    m.type = msg_type
    m.content = content
    m.tool_calls = tool_calls or []
    return m


class TestMsgToDict:
    def test_ai_message_with_tool_calls(self):
        msg = _msg("ai", "Calling traffic_send", [
            {"name": "traffic_send", "args": {"dst_ip": "10.99.80.160", "pps": 100}, "id": "t1"},
            {"name": "ping_rtt", "args": {"ip": "10.99.80.160"}, "id": "t2"},
        ])
        result = _msg_to_dict(msg)

        assert result["role"] == "ai"
        assert result["content"] == "Calling traffic_send"
        assert result["tool_calls"] == [
            {"name": "traffic_send", "args": {"dst_ip": "10.99.80.160", "pps": 100}},
            {"name": "ping_rtt", "args": {"ip": "10.99.80.160"}},
        ]

    def test_message_without_tool_calls_has_none(self):
        msg = _msg("ai", "plain text reply")
        result = _msg_to_dict(msg)

        assert result["role"] == "ai"
        assert result["content"] == "plain text reply"
        assert result["tool_calls"] is None

    def test_tool_message_role_preserved(self):
        msg = _msg("tool", '{"success": true}')
        result = _msg_to_dict(msg)

        assert result["role"] == "tool"
        assert result["tool_calls"] is None

    def test_missing_attributes_use_defaults(self):
        m = MagicMock(spec=[])
        result = _msg_to_dict(m)

        assert result["role"] == "unknown"
        assert result["content"] == ""
        assert result["tool_calls"] is None
