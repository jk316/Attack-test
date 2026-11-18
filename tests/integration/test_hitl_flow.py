"""HITL 审批闭环集成测试（007-T007）。

真实 build_graph + fake 模型 + 真实 interrupt() 暂停：断言
① hitl_request 推送（data 含 message+params）
② 队列回填后 resume 决定送达（hitl_response 回显）
③ 拒绝时该工具结果标记「被操作员拒绝」且零流量（traffic_send_tool 未被调用）。
参照 tests/e2e 的 mock 模型模式；所有流量工具层被 mock，零真实流量。
"""

import asyncio

import pytest
from langchain_core.messages import AIMessage

from backend import experiment as exp_mod


def _make_ai(tool_calls, content=""):
    if tool_calls is None:
        return AIMessage(content=content, tool_calls=[])
    return AIMessage(
        content=content,
        tool_calls=[
            {"name": tc["name"], "args": tc.get("args", {}), "id": tc.get("id", f"call_{i}")}
            for i, tc in enumerate(tool_calls)
        ],
    )


def _build_mock_model(responses):
    from unittest.mock import AsyncMock, MagicMock
    model = MagicMock()
    model.model_name = "deepseek-chat"
    model.bind_tools.return_value = model
    model.invoke.side_effect = responses        # 同步路径
    model.ainvoke = AsyncMock(side_effect=responses)  # 异步路径（web graph.ainvoke）
    return model


class FakeWS:
    def __init__(self):
        self.sent = []
        self.hitl_request_seen = asyncio.Event()

    async def send_json(self, data):
        self.sent.append(data)
        if data.get("type") == "hitl_request":
            self.hitl_request_seen.set()


class TestHitlClosedLoop:
    @pytest.mark.asyncio
    async def test_reject_stops_tool_with_zero_traffic(self):
        """拒绝决定：工具零执行，结果标记「被操作员拒绝」。"""
        from unittest.mock import patch

        from src.agent import graph as graph_mod

        model = _build_mock_model([
            _make_ai([{
                "name": "traffic_send",
                "args": {"dst_ip": "10.99.80.160", "dst_port": 8080, "pps": 50},
                "id": "c1",
            }]),
            _make_ai(None, "实验中止：操作员拒绝了流量发送。"),
        ])

        # ⚠️ 安全红线：patch 必须覆盖整个 start/approve 生命周期——
        # 若 patch 在 start 前退出，真实 Scapy 工具会向 allowlist 目标发流。
        with patch.object(graph_mod, "_build_model", return_value=model), \
             patch("src.agent.tools.traffic_send_tool") as mock_send, \
             patch.object(exp_mod, "build_graph",
                          side_effect=graph_mod.build_graph) as mock_build:
            manager = exp_mod.ExperimentManager()
            mock_build.assert_called()  # 真实 build_graph 经 backend 命名空间构建

            ws = FakeWS()
            task = asyncio.create_task(manager.start("A", {
                "target_ip": "10.99.80.160", "max_iters": 3, "no_improve_limit": 2,
            }, ws))

            await asyncio.wait_for(ws.hitl_request_seen.wait(), timeout=30)

            # ① hitl_request 推送：data 含 message + params
            hitl_requests = [m for m in ws.sent if m["type"] == "hitl_request"]
            assert hitl_requests, "未收到 hitl_request"
            data = hitl_requests[0]["data"]
            assert "message" in data and "params" in data
            assert "10.99.80.160" in str(data["params"])

            # ② 队列回填后 resume 决定送达（拒绝）
            assert await manager.approve("A", False) == "applied"

            await asyncio.wait_for(task, timeout=60)

            # hitl_response 回显 approved=False
            responses = [m for m in ws.sent if m["type"] == "hitl_response"]
            assert responses and responses[0]["data"]["approved"] is False

            # ③ 拒绝 → 零流量：traffic_send_tool 从未被调用
            mock_send.assert_not_called()

            # 工具结果标记「被操作员拒绝」
            tool_results = [m for m in ws.sent if m["type"] == "tool_result"]
            assert tool_results, "缺少工具结果推送"
            assert any("HITL rejected by operator" in tr["data"]["content"]
                       for tr in tool_results)

            # 实验正常结束
            done = [m for m in ws.sent if m["type"] == "experiment_done"]
            assert done

    @pytest.mark.asyncio
    async def test_approve_continues_to_completion(self):
        """批准决定：实验继续直至完成（工具层 mock 成功）。"""
        from unittest.mock import patch

        from src.agent import graph as graph_mod

        model = _build_mock_model([
            _make_ai([{
                "name": "traffic_send",
                "args": {"dst_ip": "10.99.80.160", "dst_port": 8080, "pps": 50},
                "id": "c1",
            }]),
            _make_ai(None, "实验完成。"),
        ])

        # ⚠️ 安全红线：patch 必须覆盖整个 start/approve 生命周期。
        with patch.object(graph_mod, "_build_model", return_value=model), \
             patch("src.agent.tools.traffic_send_tool") as mock_send, \
             patch.object(exp_mod, "build_graph",
                          side_effect=graph_mod.build_graph):
            manager = exp_mod.ExperimentManager()

            mock_send.return_value = {"success": True, "packets_sent": {"total": 250}}

            ws = FakeWS()
            task = asyncio.create_task(manager.start("A", {
                "target_ip": "10.99.80.160", "max_iters": 3, "no_improve_limit": 2,
            }, ws))

            await asyncio.wait_for(ws.hitl_request_seen.wait(), timeout=30)
            assert await manager.approve("A", True) == "applied"

            await asyncio.wait_for(task, timeout=60)

            mock_send.assert_called_once()
            responses = [m for m in ws.sent if m["type"] == "hitl_response"]
            assert responses and responses[0]["data"]["approved"] is True
            done = [m for m in ws.sent if m["type"] == "experiment_done"]
            assert done
