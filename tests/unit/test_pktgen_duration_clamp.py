"""duration 下发钳制测试（008-T008）。

>60000 的 duration 经 src/pktgen/adapter.py 的 _run_traffic_tool/_execute_skill
路径后，下发给引擎的 duration ≤60000（FR-007、宪法附加约束）。
语义分层：工具层（005-G1）拒绝超限请求（LLM 可见参数错误）；
_execute_skill 为引擎边界守卫，任何内部调用方下发的 duration 均被钳制。
"""

from unittest.mock import MagicMock, patch

import pytest

ALLOWED_IP = "10.99.80.160"


class TestDurationClampAtEngineBoundary:
    def test_execute_skill_clamps_duration(self):
        """_execute_skill 直接收到 duration=120000 → 引擎收到 60000。"""
        from src.pktgen import adapter

        with patch.object(adapter, "is_dry_run", return_value=True), \
             patch.object(adapter, "_import_pktgen") as mock_imp:
            mock_dry = MagicMock(return_value={"success": True, "mode": "dry_run"})
            mock_imp.return_value = (mock_dry, MagicMock())

            adapter._execute_skill("udp_flood", {"rate": 50, "duration": 120000})

            engine_params = mock_dry.call_args[0][1]
            assert engine_params["duration"] == 60000

    def test_execute_skill_leaves_valid_duration_untouched(self):
        """duration ≤60000 原样下发。"""
        from src.pktgen import adapter

        with patch.object(adapter, "is_dry_run", return_value=True), \
             patch.object(adapter, "_import_pktgen") as mock_imp:
            mock_dry = MagicMock(return_value={"success": True, "mode": "dry_run"})
            mock_imp.return_value = (mock_dry, MagicMock())

            adapter._execute_skill("udp_flood", {"rate": 50, "duration": 5000})

            engine_params = mock_dry.call_args[0][1]
            assert engine_params["duration"] == 5000

    def test_run_traffic_tool_rejects_over_limit(self):
        """工具层语义不变（005-G1）：超限请求被拒绝、零编译零流量。"""
        from src.pktgen import adapter
        from src.pktgen.adapter import pktgen_udp_flood

        with patch.object(adapter, "_execute_skill") as mock_exec:
            result = pktgen_udp_flood.invoke({
                "dst_ip": ALLOWED_IP, "rate": 50, "duration": 120000,
            })

        assert result["success"] is False
        assert "60000" in result["error"]
        mock_exec.assert_not_called()
