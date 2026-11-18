"""resume=False 零流量语义单测（007-T011）。

对 ExperimentManager 会话的 approve(False) 路径断言注入的决定为 False
（Command(resume=False) 语义），并在工具层断言拒绝返回
`{"success": false, "error": "HITL rejected by operator"}`（与 008 契约一致）。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend import experiment as exp_mod


class FakeWS:
    def __init__(self):
        self.sent = []
        self.hitl_request_seen = asyncio.Event()

    async def send_json(self, data):
        self.sent.append(data)
        if data.get("type") == "hitl_request":
            self.hitl_request_seen.set()


def _paused_state():
    msgs = [
        MagicMock(type="human", content="start", tool_calls=[]),
        MagicMock(type="ai", content="calling tool",
                  tool_calls=[{"name": "traffic_send", "args": {}, "id": "c1"}]),
    ]
    gs = MagicMock()
    gs.next = ("tools",)
    gs.values = {"messages": msgs}
    gs.tasks = [MagicMock(interrupts=[MagicMock(
        value={"message": "[HITL] Approve?", "params": {"pps": 10}})])]
    return gs


def _done_state():
    msgs = [
        MagicMock(type="human", content="start", tool_calls=[]),
        MagicMock(type="ai", content="calling tool",
                  tool_calls=[{"name": "traffic_send", "args": {}, "id": "c1"}]),
        MagicMock(type="tool", content='{"success": false, "error": "HITL rejected by operator"}',
                  tool_calls=[]),
        MagicMock(type="ai", content="stopped", tool_calls=[]),
    ]
    gs = MagicMock()
    gs.next = ()
    gs.values = {"messages": msgs}
    gs.tasks = []
    return gs


class TestResumeFalseSemantics:
    @pytest.mark.asyncio
    async def test_approve_false_injects_false_resume(self):
        """approve(False) → Command(resume=False)，工具层零执行。"""
        resumed = []

        fake_graph = MagicMock()
        async def fake_ainvoke(state, config):
            if isinstance(state, exp_mod.Command):
                resumed.append(state.resume)
            return None

        fake_graph.ainvoke = AsyncMock(side_effect=fake_ainvoke)

        _calls = {"n": 0}

        def _get_state(config):
            _calls["n"] += 1
            return _paused_state() if _calls["n"] <= 2 else _done_state()

        fake_graph.get_state = MagicMock(side_effect=_get_state)

        with patch.object(exp_mod, "build_graph", return_value=fake_graph):
            manager = exp_mod.ExperimentManager()
        session = manager._get_session("A")
        session._graph = fake_graph
        session._running = True
        session._config = {"configurable": {"thread_id": "t"}}
        ws = FakeWS()
        session._ws = ws
        session._connected = True

        task = asyncio.create_task(
            session._run_loop({"messages": [{"role": "user", "content": "start"}]})
        )
        await asyncio.wait_for(ws.hitl_request_seen.wait(), timeout=5)

        assert await manager.approve("A", False) == "applied"

        await asyncio.wait_for(task, timeout=10)

        assert resumed == [False]  # Command(resume=False) 语义
        # 回显拒绝决定
        responses = [m for m in ws.sent if m["type"] == "hitl_response"]
        assert responses and responses[0]["data"]["approved"] is False

    def test_tool_layer_returns_hitl_rejected_on_false(self):
        """工具层：拒绝返回 {"success": false, "error": "HITL rejected by operator"}。"""
        from src.pktgen import adapter as pktgen_adapter
        from src.agent import tools as agent_tools

        # Scapy 工具层（traffic_send wrapper）
        with patch.object(agent_tools, "interrupt", return_value=False):
            result = agent_tools.traffic_send.invoke({
                "dst_ip": "10.99.80.160", "dst_port": 8080,
            })
        assert result["success"] is False
        assert "HITL rejected" in result["error"]

        # Pktgen 工具层
        with patch.object(pktgen_adapter, "is_dry_run", return_value=False), \
             patch.object(pktgen_adapter, "interrupt", return_value=False):
            result = pktgen_adapter.pktgen_udp_flood.invoke({
                "dst_ip": "10.99.80.160", "rate": 50, "duration": 1000,
            })
        assert result["success"] is False
        assert "HITL rejected" in result["error"]
