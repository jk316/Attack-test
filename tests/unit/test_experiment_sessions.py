"""会话模型单元测试（007-T006）：per-client_id 注册表、所有者校验、互斥。

覆盖：同 client_id 二次 start 被拒（FR-009 会话粒度）；B 客户端的
hitl_response/stop_experiment 对 A 会话无效且收到 not_owner；A 自己的决定
生效且每个审批请求恰好消费一次；R7 监控清理与 R8 画像映射注入。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend import experiment as exp_mod

ALLOWED_IP = "10.99.80.160"


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


def _empty_state():
    gs = MagicMock()
    gs.next = ()
    gs.values = {"messages": [MagicMock(type="human", content="start", tool_calls=[])]}
    gs.tasks = []
    return gs


def _make_manager():
    """ExperimentManager with a fake graph (no LLM, no network)."""
    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock()
    fake_graph.get_state = MagicMock(return_value=_empty_state())
    with patch.object(exp_mod, "build_graph", return_value=fake_graph):
        manager = exp_mod.ExperimentManager()
    session = manager._get_session("A")
    session._graph = fake_graph
    return manager, fake_graph, session


def _params(**overrides):
    params = {"target_ip": ALLOWED_IP, "max_iters": 20, "no_improve_limit": 5}
    params.update(overrides)
    return params


class TestSessionRegistry:
    def test_running_reflects_any_session(self):
        manager, _, session = _make_manager()
        assert manager.running is False
        session._running = True
        assert manager.running is True

    def test_session_created_once_per_client(self):
        manager, _, _ = _make_manager()
        s1 = manager._get_session("A")
        s2 = manager._get_session("A")
        assert s1 is s2
        sb = manager._get_session("B")
        assert sb is not s1


class TestStartExclusivity:
    @pytest.mark.asyncio
    async def test_same_client_second_start_rejected(self):
        manager, fake_graph, _ = _make_manager()
        blocker = asyncio.Event()

        async def _block(*a, **k):
            await blocker.wait()

        fake_graph.ainvoke = AsyncMock(side_effect=_block)

        ws1, ws2 = FakeWS(), FakeWS()
        task = asyncio.create_task(manager.start("A", _params(), ws1))
        await asyncio.sleep(0.05)  # 让 start 置 running 并进入 ainvoke

        await manager.start("A", _params(), ws2)
        assert any(
            m["type"] == "error" and "已在运行" in m["data"]["message"]
            for m in ws2.sent
        )

        blocker.set()
        await asyncio.wait_for(task, timeout=5)

    @pytest.mark.asyncio
    async def test_invalid_budget_params_rejected_before_start(self):
        manager, fake_graph, _ = _make_manager()
        ws = FakeWS()
        await manager.start("A", _params(max_iters=0), ws)
        assert any(
            m["type"] == "error" and "max_iters" in m["data"]["message"]
            for m in ws.sent
        )
        fake_graph.ainvoke.assert_not_called()


class TestOwnerAuthorization:
    @pytest.mark.asyncio
    async def test_other_client_cannot_approve_or_stop(self):
        manager, fake_graph, _ = _make_manager()
        blocker = asyncio.Event()

        async def _block(*a, **k):
            await blocker.wait()

        fake_graph.ainvoke = AsyncMock(side_effect=_block)

        ws = FakeWS()
        task = asyncio.create_task(manager.start("A", _params(), ws))
        await asyncio.sleep(0.05)

        # B 客户端对 A 会话的审批与停止：not_owner 且状态不变
        assert await manager.approve("B", True) == "not_owner"
        assert await manager.stop("B") == "not_owner"
        session = manager._get_session("A")
        assert session.running is True
        assert session._stop_requested is False

        # B 未启动过实验（无会话）时同样 not_owner
        assert await manager.approve("C", True) == "not_owner"

        blocker.set()
        await asyncio.wait_for(task, timeout=5)

    @pytest.mark.asyncio
    async def test_owner_decision_applied_exactly_once(self):
        manager, _, session = _make_manager()
        session._running = True
        session._hitl_pending = True

        assert await manager.approve("A", True) == "applied"
        assert session._hitl_queue.get_nowait() is True

        # 同一审批请求的第二次决定被忽略（每请求恰好消费一次）
        assert await manager.approve("A", True) == "ignored"
        assert session._hitl_queue.empty()

    @pytest.mark.asyncio
    async def test_stop_unblocks_pending_hitl(self):
        manager, _, session = _make_manager()
        session._running = True
        session._hitl_pending = True

        assert await manager.stop("A") == "applied"
        assert session._stop_requested is True
        assert session._hitl_queue.get_nowait() is False  # 停止优先：拒绝值终结阻塞


class TestR7PingMonitorCleanup:
    @pytest.mark.asyncio
    async def test_ping_monitor_stopped_when_session_ends(self):
        """R7（003-T018）：实验结束后监控被清理（无残留探测进程）。"""
        manager, fake_graph, _ = _make_manager()
        fake_graph.ainvoke = AsyncMock(return_value=None)
        fake_graph.get_state = MagicMock(return_value=_empty_state())

        mock_monitor = MagicMock()
        mock_monitor.is_running.return_value = True
        with patch.object(exp_mod, "get_ping_monitor", return_value=mock_monitor):
            await manager.start("A", _params(), FakeWS())

        mock_monitor.stop.assert_called()


class TestR8ProfileMappingInjection:
    @pytest.mark.asyncio
    async def test_pcap_profile_mapping_injected_into_session_context(self, monkeypatch):
        """R8（004-T017）：上传画像后走 profile_to_params 映射注入 user message。"""
        manager, fake_graph, _ = _make_manager()
        captured = {}
        fake_graph.ainvoke = AsyncMock(
            side_effect=lambda state, config: captured.update(state) or None
        )

        def fake_pcap_profile_tool(**kwargs):
            return {"ips": ["10.99.80.160"], "total_packets": 10}

        def fake_profile_to_params(profile, defaults=None):
            assert defaults is not None  # 与 CLI 一致：携带默认值
            return {"dst_port": 53, "packet_size": 128, "flow_count": 8, "pps": 100}

        import importlib
        ppt = importlib.import_module("src.tools.pcap_profile_tool")
        ptp = importlib.import_module("src.tools.profile_to_params")
        monkeypatch.setattr(ppt, "pcap_profile_tool", fake_pcap_profile_tool)
        monkeypatch.setattr(ptp, "profile_to_params", fake_profile_to_params)

        await manager.start("A", _params(pcap_path="data/uploads/ab12cd34_x.pcap"),
                            FakeWS())

        user_content = captured["messages"][0]["content"]
        assert "画像映射初始参数: dst_port=53, packet_size=128, flow_count=8, pps=100" \
            in user_content
        assert "PCAP文件路径: data/uploads/ab12cd34_x.pcap" in user_content

    @pytest.mark.asyncio
    async def test_profile_failure_falls_back_with_notice(self, monkeypatch):
        """画像分析失败时不中断启动，注入失败提示并继续。"""
        manager, fake_graph, _ = _make_manager()
        captured = {}
        fake_graph.ainvoke = AsyncMock(
            side_effect=lambda state, config: captured.update(state) or None
        )

        def boom(**kwargs):
            raise FileNotFoundError("no such pcap")

        import importlib
        ppt = importlib.import_module("src.tools.pcap_profile_tool")
        monkeypatch.setattr(ppt, "pcap_profile_tool", boom)

        await manager.start("A", _params(pcap_path="data/uploads/missing.pcap"),
                            FakeWS())

        user_content = captured["messages"][0]["content"]
        assert "画像分析失败" in user_content
