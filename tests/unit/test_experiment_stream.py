"""消息流顺序/类型单测（007-T008）。

mock graph 状态快照，断言 `_push_new_messages(since)` 从 since 起无遗漏、
tool 角色映射为 tool_result、其余映射为 messages。
"""

from unittest.mock import MagicMock

import pytest

from backend.experiment import ExperimentSession


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


def _msg(role, content, tool_calls=None):
    m = MagicMock()
    m.type = role
    m.content = content
    m.tool_calls = tool_calls or []
    return m


def _make_session(messages):
    fake_graph = MagicMock()
    fake_graph.get_state = MagicMock(return_value=_state(messages))
    session = ExperimentSession.__new__(ExperimentSession)  # 不触发图构建
    session._graph = fake_graph
    session._config = {"configurable": {"thread_id": "t"}}
    session._ws = FakeWS()
    session._connected = True
    session._hitl_queue = None
    return session, fake_graph


def _state(messages):
    gs = MagicMock()
    gs.values = {"messages": messages}
    return gs


class TestPushNewMessages:
    @pytest.mark.asyncio
    async def test_streams_all_from_since_without_gaps(self):
        messages = [
            _msg("human", "start"),
            _msg("ai", "calling tool", [{"name": "traffic_send", "args": {}, "id": "c1"}]),
            _msg("tool", '{"success": true}'),
            _msg("ai", "done"),
        ]
        session, _ = _make_session(messages)

        await session._push_new_messages(1)

        types = [m["type"] for m in session._ws.sent]
        assert types == ["messages", "tool_result", "messages"]
        # 从 since 起无遗漏：ai(工具调用) → tool → ai
        first_batch = session._ws.sent[0]["data"]
        assert first_batch[0]["content"] == "calling tool"
        assert first_batch[0]["tool_calls"] == [
            {"name": "traffic_send", "args": {}}
        ]
        tool_result = session._ws.sent[1]["data"]
        assert tool_result["role"] == "tool"
        assert tool_result["content"] == '{"success": true}'
        assert session._ws.sent[2]["data"][0]["content"] == "done"

    @pytest.mark.asyncio
    async def test_since_zero_includes_human_message(self):
        messages = [_msg("human", "start"), _msg("ai", "hi")]
        session, _ = _make_session(messages)

        await session._push_new_messages(0)

        assert session._ws.sent[0]["type"] == "messages"
        assert session._ws.sent[0]["data"][0]["role"] == "human"

    @pytest.mark.asyncio
    async def test_no_state_pushes_nothing(self):
        session, fake_graph = _make_session([])
        fake_graph.get_state.return_value = None

        await session._push_new_messages(0)

        assert session._ws.sent == []

    @pytest.mark.asyncio
    async def test_no_new_messages_pushes_nothing(self):
        messages = [_msg("ai", "hi")]
        session, _ = _make_session(messages)

        await session._push_new_messages(1)

        assert session._ws.sent == []


class TestExtractHitlCompat:
    """T009：_extract_hitl 与统一审批结构（contracts/hitl-payload.md）兼容。"""

    def test_extracts_dict_with_message_key(self):
        gs = MagicMock()
        intr = MagicMock()
        intr.value = {"message": "[HITL] Approve?", "params": {"pps": 10}}
        gs.tasks = [MagicMock(interrupts=[intr])]
        result = ExperimentSession._extract_hitl(gs)
        assert result == {"message": "[HITL] Approve?", "params": {"pps": 10}}

    def test_passes_scope_through_unchanged(self):
        """008 统一结构新增 scope 字段：透传原样，不报错。"""
        gs = MagicMock()
        intr = MagicMock()
        intr.value = {
            "message": "[HITL] Approve?",
            "params": {"dst_ip": "10.99.80.160"},
            "scope": {"tool": "traffic_send", "mode": "live"},
        }
        gs.tasks = [MagicMock(interrupts=[intr])]
        result = ExperimentSession._extract_hitl(gs)
        assert result["scope"] == {"tool": "traffic_send", "mode": "live"}

    def test_payload_without_scope_still_works(self):
        """旧 payload 无 scope：兼容，不报错、不注入默认值。"""
        gs = MagicMock()
        intr = MagicMock()
        intr.value = {"message": "[HITL] Approve?", "params": {}}
        gs.tasks = [MagicMock(interrupts=[intr])]
        result = ExperimentSession._extract_hitl(gs)
        assert "scope" not in result

    def test_non_dict_interrupts_ignored(self):
        gs = MagicMock()
        intr = MagicMock()
        intr.value = "not a dict"
        gs.tasks = [MagicMock(interrupts=[intr])]
        assert ExperimentSession._extract_hitl(gs) is None
