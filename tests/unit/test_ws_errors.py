"""断线与错误消息测试（007-T018）。

无效 JSON → error（"无效的 JSON"）；未知消息类型 → error（"未知消息类型: …"）
且实验状态不变；WebSocketDisconnect 后会话标记断开、服务不崩溃、实验继续
（FR-019/FR-020）。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend import server as server_mod


@pytest.fixture
def test_client():
    with TestClient(server_mod.app) as client:
        yield client


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


class TestWsErrors:
    def test_invalid_json_gets_error(self, test_client):
        with test_client.websocket_connect("/ws/CERR1") as ws:
            ws.receive_json()  # status connected
            ws.send_text("this is not json {{{{")
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "无效的 JSON" in msg["data"]["message"]

    def test_unknown_message_type_gets_error(self, test_client):
        with test_client.websocket_connect("/ws/CERR2") as ws:
            ws.receive_json()  # status connected
            ws.send_json({"type": "bogus_type"})
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "未知消息类型: bogus_type" == msg["data"]["message"]

    def test_unknown_type_does_not_change_experiment_state(self, test_client):
        """未知消息类型 → error 且实验状态不变。"""
        manager = server_mod.manager
        assert manager.running is False
        with test_client.websocket_connect("/ws/CERR3") as ws:
            ws.receive_json()
            ws.send_json({"type": "bogus_type"})
            msg = ws.receive_json()
            assert msg["type"] == "error"
        assert manager.running is False  # 状态不变

    def test_disconnect_marks_session_and_server_survives(self, test_client):
        """WebSocketDisconnect：会话标记断开、服务不崩溃（后续请求正常）。"""
        manager = server_mod.manager
        session = manager._get_session("CDISC")
        session._connected = True
        with test_client.websocket_connect("/ws/CDISC") as ws:
            ws.receive_json()  # status connected
            ws.send_json({"type": "hitl_response", "data": {"approved": True}})
            # 会话未运行 → 非会话所有者 error（确认路由正常）
            msg = ws.receive_json()
            assert msg["type"] == "error"
        # 连接关闭 → 服务端标记断开
        assert session.connected is False
        # 服务不崩溃：后续 HTTP 请求正常
        resp = test_client.get("/api/experiment/status")
        assert resp.status_code == 200
        assert resp.json() == {"running": False}


class TestExperimentSurvivesDisconnect:
    @pytest.mark.asyncio
    async def test_run_loop_continues_after_disconnect(self):
        """断线后实验继续（推送静默降级，不中断图执行）。"""
        manager = server_mod.manager
        session = manager._get_session("CSURV")
        fake_graph = MagicMock()
        fake_graph.ainvoke = AsyncMock(return_value=None)
        fake_graph.get_state = MagicMock(return_value=_done_state())
        session._graph = fake_graph

        sent = []

        class FakeWS:
            async def send_json(self, data):
                sent.append(data)

        session._ws = FakeWS()
        session._connected = True

        task = asyncio.create_task(session.start({
            "target_ip": "10.99.80.160", "max_iters": 3, "no_improve_limit": 2,
        }, session._ws))
        await asyncio.sleep(0.05)
        # 模拟服务端收到断线
        manager.mark_disconnected("CSURV")

        await asyncio.wait_for(task, timeout=10)
        # 实验完成（不因断线崩溃/终止）
        assert fake_graph.ainvoke.await_count >= 1
        assert session.running is False
        # 断线前的推送保留；断线后的推送被安全降级（不再崩溃）
        assert any(m["type"] == "status" for m in sent)
