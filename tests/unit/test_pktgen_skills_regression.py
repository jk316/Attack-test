"""Pktgen 五工具契约回归测试 — range_scan / packet_sequence / pcap_replay /
stats_monitor / stop_and_reset（005-T015，US3）。

纯适配器行为、mock 网络 I/O、无硬件依赖。锁定 FR-005（allowlist）、
FR-006（HITL）、FR-007（免 HITL）、FR-013（非法 JSON 拒绝）与
决策 005-2（dry-run 下 stop/stats 仅编译不连接硬件）。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

ALLOWLISTED_IP = "10.99.80.160"


class TestRangeScan:
    """range_scan 参数传递与 dst_ip allowlist（FR-005）。"""

    def test_params_forwarded_to_executor(self):
        """scan_field/start/min/max/inc 正确映射进编译参数。"""
        from src.pktgen.adapter import pktgen_range_scan

        with patch("src.pktgen.adapter._execute_skill") as mock_exec, \
             patch("src.pktgen.adapter._hitl_gate", return_value=True), \
             patch("src.pktgen.adapter.validate_target"):
            mock_exec.return_value = {"success": True}

            pktgen_range_scan.invoke({
                "dst_ip": ALLOWLISTED_IP, "scan_field": "dst_port",
                "start": "1", "min_val": "1", "max_val": "100", "inc": "1",
                "rate": 50,
            })

            _, params = mock_exec.call_args[0]
            assert params["scan_field"] == "dst_port"
            assert params["start"] == "1"
            assert params["min"] == "1"
            assert params["max"] == "100"
            assert params["inc"] == "1"
            assert params["dst_ip"] == ALLOWLISTED_IP

    def test_dst_ip_allowlist_enforced(self):
        """dst_ip 必须过 allowlist（FR-005）。"""
        from src.pktgen.adapter import pktgen_range_scan

        with patch("src.pktgen.adapter._execute_skill"), \
             patch("src.pktgen.adapter._hitl_gate", return_value=True):
            with pytest.raises(ValueError, match="not in allowlist"):
                pktgen_range_scan.invoke({
                    "dst_ip": "192.168.1.99", "scan_field": "dst_port",
                    "start": "1", "min_val": "1", "max_val": "100", "inc": "1",
                })


class TestPacketSequenceContracts:
    """packet_sequence 非法 JSON 拒绝（FR-013）与条目转发语义。"""

    def test_invalid_json_rejected(self):
        """非法 JSON 返回错误 dict，不抛异常、不执行。"""
        from src.pktgen.adapter import pktgen_packet_sequence

        with patch("src.pktgen.adapter._execute_skill") as mock_exec, \
             patch("src.pktgen.adapter.validate_target"):
            result = pktgen_packet_sequence.invoke({
                "dst_ip": ALLOWLISTED_IP, "sequences": "not valid json {{{",
            })

        assert result["success"] is False
        assert "Invalid JSON" in result["error"]
        mock_exec.assert_not_called()

    def test_entries_forwarded_unchanged(self):
        """≤16 条目语义：适配器原样转发列表（16 上限为 YAML 文档语义，
        编译期表语义，适配器不重复实现）。"""
        from src.pktgen.adapter import pktgen_packet_sequence

        entries = []
        for i in range(4):
            entries.append({
                "eth_dst_addr": "00:11:44:55:66:77",
                "eth_src_addr": "00:11:12:34:56:78",
                "ip_dst_addr": ALLOWLISTED_IP,
                "ip_src_addr": "10.0.0.1",
                "sport": i, "dport": i,
                "ethType": "0x0800", "ipProto": 1,
                "vlanid": 0, "pktSize": 64,
            })

        with patch("src.pktgen.adapter._execute_skill") as mock_exec, \
             patch("src.pktgen.adapter._hitl_gate", return_value=True), \
             patch("src.pktgen.adapter.validate_target"):
            mock_exec.return_value = {"success": True}
            pktgen_packet_sequence.invoke({
                "dst_ip": ALLOWLISTED_IP,
                "sequences": json.dumps(entries),
                "rate": 50,
            })

        _, params = mock_exec.call_args[0]
        assert len(params["sequences"]) == 4
        assert params["sequences"][3]["sport"] == 3


class TestPcapReplayGates:
    """pcap_replay 免 allowlist（FR-005）且需 HITL（FR-006）。"""

    def test_skips_allowlist(self):
        """pcap_replay 无 dst_ip：不调用 allowlist 校验。"""
        from src.pktgen.adapter import pktgen_pcap_replay

        with patch("src.pktgen.adapter._execute_skill") as mock_exec, \
             patch("src.pktgen.adapter.validate_target") as mock_validate:
            mock_exec.return_value = {"success": True}
            result = pktgen_pcap_replay.invoke({"pcap_file": "/tmp/test.pcap", "rate": 50})

            assert result["success"] is True
            mock_validate.assert_not_called()

    def test_hitl_required_in_live_mode(self):
        """live 模式下 pcap_replay 必须过 HITL 审批。"""
        from src.pktgen.adapter import pktgen_pcap_replay

        with patch("src.pktgen.adapter.is_dry_run", return_value=False), \
             patch("src.pktgen.adapter._execute_skill") as mock_exec, \
             patch("src.pktgen.adapter.interrupt", return_value=True) as mock_int:
            mock_exec.return_value = {"success": True, "mode": "live"}
            result = pktgen_pcap_replay.invoke({"pcap_file": "/tmp/test.pcap", "rate": 50})

            assert result["success"] is True
            mock_int.assert_called_once()

    def test_hitl_rejection_blocks_execution(self):
        """HITL 拒绝时零执行。"""
        from src.pktgen.adapter import pktgen_pcap_replay

        with patch("src.pktgen.adapter.is_dry_run", return_value=False), \
             patch("src.pktgen.adapter._execute_skill") as mock_exec, \
             patch("src.pktgen.adapter.interrupt", return_value=False):
            result = pktgen_pcap_replay.invoke({"pcap_file": "/tmp/test.pcap", "rate": 50})

            assert result["success"] is False
            assert "HITL" in result["error"]
            mock_exec.assert_not_called()


class TestOpsToolsNoHitl:
    """stats_monitor 与 stop_and_reset 免 HITL 且任意模式可调用（FR-007）。"""

    @pytest.mark.parametrize("tool_name", ["pktgen_stats_monitor", "pktgen_stop_and_reset"])
    def test_no_hitl_in_any_mode(self, tool_name):
        """dry-run 与 live 两种模式下均不触发 interrupt，且正常执行。"""
        from src.pktgen import adapter

        tool = getattr(adapter, tool_name)
        for dry_run in (True, False):
            with patch.object(adapter, "is_dry_run", return_value=dry_run), \
                 patch.object(adapter, "_execute_skill") as mock_exec, \
                 patch.object(adapter, "interrupt") as mock_int:
                mock_exec.return_value = {"success": True, "mode": "dry_run" if dry_run else "live"}
                result = tool.invoke({})

                assert result["success"] is True
                mock_int.assert_not_called()
                mock_exec.assert_called_once()

    @pytest.mark.parametrize("tool_name", ["pktgen_stats_monitor", "pktgen_stop_and_reset"])
    def test_dry_run_compiles_only_no_hardware_connection(self, tool_name):
        """决策 005-2：dry-run 下 stop/stats 仅编译（execute_skill_dry_run），
        绝不调用 live 下发。"""
        from src.pktgen import adapter

        tool = getattr(adapter, tool_name)
        with patch.object(adapter, "is_dry_run", return_value=True), \
             patch.object(adapter, "_import_pktgen") as mock_imp:
            mock_dry = MagicMock(return_value={"success": True, "mode": "dry_run"})
            mock_live = MagicMock()
            mock_imp.return_value = (mock_dry, mock_live)

            result = tool.invoke({})

            assert result["success"] is True
            mock_dry.assert_called_once()
            mock_live.assert_not_called()
