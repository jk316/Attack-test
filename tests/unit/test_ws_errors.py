"""断线与错误消息测试（007-T018）。

无效 JSON → error（"无效的 JSON"）；未知消息类型 → error（"未知消息类型: …"）
且实验状态不变（FR-019）。
"""

import pytest
from fastapi.testclient import TestClient

from backend import server as server_mod


@pytest.fixture
def test_client():
    with TestClient(server_mod.app) as client:
        yield client


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
