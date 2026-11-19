"""状态/停止会话语义集成测试（007-T017）。

GET /api/experiment/status 的 running 值与面板一致；POST /api/experiment/stop
受理后实验结束消息推送且状态复位（FR-017/FR-018、SC-008/009）。
使用 httpx ASGITransport 与测试同一事件循环，避免跨 loop 队列问题。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend import experiment as exp_mod
from backend import server as server_mod

TRANSPORT = httpx.ASGITransport(app=server_mod.app)


@pytest.fixture
def client():
    async def _req(method, path, **kwargs):
        async with httpx.AsyncClient(transport=TRANSPORT,
                                     base_url="http://test") as c:
            return await c.request(method, path, **kwargs)
    return _req


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
        value={"message": "[HITL] Approve?", "params": {}})])]
    return gs


def _done_state():
    msgs = [
        MagicMock(type="human", content="start", tool_calls=[]),
        MagicMock(type="ai", content="done", tool_calls=[]),
    ]
    gs = MagicMock()
    gs.next = ()
    gs.values = {"messages": msgs}
    gs.tasks = []
    return gs


class FakeWS:
    def __init__(self):
        self.sent = []
        self.done_seen = asyncio.Event()

    async def send_json(self, data):
        self.sent.append(data)
        if data.get("type") == "experiment_done":
            self.done_seen.set()


class TestStatusStopSemantics:
    @pytest.mark.asyncio
    async def test_status_reflects_running(self, client, monkeypatch):
        """status 的 running 值与面板一致（manager.running）。"""
        manager = server_mod.manager
        session = manager._get_session("ST1")

        resp = await client("GET", "/api/experiment/status")
        assert resp.status_code == 200
        assert resp.json() == {"running": False}

        session._running = True
        try:
            resp = await client("GET", "/api/experiment/status")
            assert resp.json() == {"running": True}
        finally:
            session._running = False

    @pytest.mark.asyncio
    async def test_rest_stop_ends_pending_experiment(self, monkeypatch):
        """通道外 stop：受理后实验结束消息推送且状态复位。"""
        fake_graph = MagicMock()
        fake_graph.ainvoke = AsyncMock(return_value=None)

        _calls = {"n": 0}

        def _get_state(config):
            _calls["n"] += 1
            return _paused_state() if _calls["n"] <= 2 else _done_state()

        fake_graph.get_state = MagicMock(side_effect=_get_state)

        # 驱动模块级 manager 的真实会话（安全红线：全程 mock graph，无流量工具参与）
        manager = server_mod.manager
        session = manager._get_session("ST2")
        session._graph = fake_graph

        ws = FakeWS()
        task = asyncio.create_task(session.start({
            "target_ip": "10.99.80.160", "max_iters": 3, "no_improve_limit": 2,
        }, ws))
        # 等待 run_loop 进入 HITL 等待（hitl_request 已推送）
        await asyncio.sleep(0.2)

        async with httpx.AsyncClient(transport=TRANSPORT,
                                     base_url="http://test") as c:
            resp = await c.post("/api/experiment/stop")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 停止优先：注入拒绝值终结 HITL 阻塞 → 循环退出 → 结束消息推送
        await asyncio.wait_for(task, timeout=10)
        assert session.running is False
        assert any(m["type"] == "experiment_done" for m in ws.sent)

        async with httpx.AsyncClient(transport=TRANSPORT,
                                     base_url="http://test") as c:
            status = await c.get("/api/experiment/status")
        assert status.json() == {"running": False}
