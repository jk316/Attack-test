"""Tests for Pktgen adapter — src/pktgen/adapter.py."""

import json
from unittest.mock import MagicMock, patch

import pytest

ALLOWLISTED_IP = "10.99.80.160"


class TestPktgenToolList:
    """PKTGEN_TOOLS 列表结构测试。"""

    def test_nine_tools_registered(self):
        """应该有 9 个 Pktgen 工具。"""
        from src.pktgen.adapter import PKTGEN_TOOLS

        assert len(PKTGEN_TOOLS) == 9

    def test_all_tool_names_prefixed(self):
        """所有工具名应以 pktgen_ 开头。"""
        from src.pktgen.adapter import PKTGEN_TOOLS

        for t in PKTGEN_TOOLS:
            assert t.name.startswith("pktgen_"), f"{t.name} should start with pktgen_"

    def test_stop_and_reset_no_hitl(self):
        """pktgen_stop_and_reset 不在 _SKILLS_WITH_HITL 中。"""
        from src.pktgen.adapter import _SKILLS_WITH_HITL

        assert "safe_stop_and_reset" not in _SKILLS_WITH_HITL

    def test_stats_monitor_no_hitl(self):
        """pktgen_stats_monitor 不在 _SKILLS_WITH_HITL 中。"""
        from src.pktgen.adapter import _SKILLS_WITH_HITL

        assert "stats_monitoring" not in _SKILLS_WITH_HITL

    def test_expected_tool_names(self):
        """验证 9 个工具的确切名称。"""
        from src.pktgen.adapter import PKTGEN_TOOLS

        names = {t.name for t in PKTGEN_TOOLS}
        expected = {
            "pktgen_udp_flood", "pktgen_tcp_flood", "pktgen_icmp_flood",
            "pktgen_arp_flood", "pktgen_range_scan", "pktgen_packet_sequence",
            "pktgen_pcap_replay", "pktgen_stats_monitor", "pktgen_stop_and_reset",
        }
        assert names == expected


class TestAllowlistEnforcement:
    """allowlist 强制校验测试。"""

    def test_non_allowlist_ip_rejected(self):
        """非 allowlist IP 应被 validate_target 拒绝。"""
        from src.tools.ping_rtt_tool import validate_target

        with pytest.raises(ValueError, match="not in allowlist"):
            validate_target("192.168.1.99")

    def test_allowlist_ip_accepted(self):
        """allowlist IP 应通过校验。"""
        from src.tools.ping_rtt_tool import validate_target

        # 不应抛出异常
        validate_target(ALLOWLISTED_IP)

    def test_udp_flood_calls_validate_target(self):
        """pktgen_udp_flood 应对 dst_ip 调用 allowlist 校验。"""
        from src.pktgen.adapter import pktgen_udp_flood

        with patch("src.pktgen.adapter._execute_skill") as mock_exec, \
             patch("src.pktgen.adapter._hitl_gate", return_value=True), \
             patch("src.pktgen.adapter.validate_target") as mock_validate:
            mock_exec.return_value = {"success": True}

            pktgen_udp_flood.invoke({"dst_ip": ALLOWLISTED_IP, "rate": 50})

            mock_validate.assert_called_once_with(ALLOWLISTED_IP)

    def test_arp_flood_skips_allowlist(self):
        """ARP flood 没有 dst_ip 参数，不应调用 allowlist 校验。"""
        from src.pktgen.adapter import pktgen_arp_flood

        with patch("src.pktgen.adapter._execute_skill") as mock_exec, \
             patch("src.pktgen.adapter._hitl_gate", return_value=True), \
             patch("src.pktgen.adapter.validate_target") as mock_validate:
            mock_exec.return_value = {"success": True}

            pktgen_arp_flood.invoke({"rate": 50})

            mock_validate.assert_not_called()

    def test_stop_and_reset_skips_allowlist(self):
        """pktgen_stop_and_reset 不应调用 allowlist 校验。"""
        from src.pktgen.adapter import pktgen_stop_and_reset

        with patch("src.pktgen.adapter._execute_skill") as mock_exec, \
             patch("src.pktgen.adapter.validate_target") as mock_validate:
            mock_exec.return_value = {"success": True}

            pktgen_stop_and_reset.invoke({})

            mock_validate.assert_not_called()

    def test_empty_dst_ip_rejected_for_dst_ip_skills(self):
        """空 dst_ip 应对 _SKILLS_WITH_DST_IP 中的技能抛出 ValueError。"""
        from src.pktgen.adapter import _apply_allowlist

        with pytest.raises(ValueError, match="requires dst_ip"):
            _apply_allowlist("", "udp_flood")

        with pytest.raises(ValueError, match="requires dst_ip"):
            _apply_allowlist(None, "tcp_flood")


class TestHitlGate:
    """HITL 门控测试。"""

    def test_hitl_skipped_in_dry_run(self):
        """dry-run 模式下 HITL 应被跳过（直接返回 True）。"""
        from src.pktgen.adapter import _hitl_gate

        with patch("src.pktgen.adapter.is_dry_run", return_value=True):
            result = _hitl_gate("udp_flood", {"rate": 50})

        assert result is True

    def test_hitl_called_in_live_mode(self):
        """live 模式下 HITL 应通过 interrupt() 触发。"""
        from src.pktgen.adapter import _hitl_gate

        with patch("src.pktgen.adapter.is_dry_run", return_value=False), \
             patch("src.pktgen.adapter.interrupt", return_value=True) as mock_int:
            result = _hitl_gate("udp_flood", {"rate": 50})

            mock_int.assert_called_once()
            assert result is True

    def test_hitl_rejection_returns_false(self):
        """HITL 被拒绝时应返回 False。"""
        from src.pktgen.adapter import _hitl_gate

        with patch("src.pktgen.adapter.is_dry_run", return_value=False), \
             patch("src.pktgen.adapter.interrupt", return_value=False):
            result = _hitl_gate("udp_flood", {"rate": 50})

            assert result is False

    def test_traffic_tool_returns_rejection_error(self):
        """流量工具在 HITL 被拒绝时应返回错误字典。"""
        from src.pktgen.adapter import pktgen_udp_flood

        with patch("src.pktgen.adapter._hitl_gate", return_value=False), \
             patch("src.pktgen.adapter.validate_target"):
            result = pktgen_udp_flood.invoke({"dst_ip": ALLOWLISTED_IP, "rate": 50})

            assert result["success"] is False
            assert "HITL" in result["error"]

    def test_stop_and_reset_no_hitl_called(self):
        """pktgen_stop_and_reset 不应触发 HITL。"""
        from src.pktgen.adapter import pktgen_stop_and_reset

        with patch("src.pktgen.adapter._execute_skill") as mock_exec, \
             patch("src.pktgen.adapter.interrupt") as mock_int:
            mock_exec.return_value = {"success": True}

            pktgen_stop_and_reset.invoke({})

            mock_int.assert_not_called()

    def test_stats_monitor_no_hitl_called(self):
        """pktgen_stats_monitor 不应触发 HITL。"""
        from src.pktgen.adapter import pktgen_stats_monitor

        with patch("src.pktgen.adapter._execute_skill") as mock_exec, \
             patch("src.pktgen.adapter.interrupt") as mock_int:
            mock_exec.return_value = {"success": True}

            pktgen_stats_monitor.invoke({})

            mock_int.assert_not_called()


class TestSkillExecution:
    """技能执行测试（dry-run / live）。"""

    def test_execute_skill_dry_run_calls_correct_function(self):
        """dry-run 模式应调用 execute_skill_dry_run。"""
        from src.pktgen.adapter import _execute_skill

        with patch("src.pktgen.adapter.is_dry_run", return_value=True), \
             patch("src.pktgen.adapter._import_pktgen") as mock_import:
            mock_dry = MagicMock(return_value={"success": True, "mode": "dry_run"})
            mock_live = MagicMock()
            mock_import.return_value = (mock_dry, mock_live)

            result = _execute_skill("udp_flood", {"rate": 50})

            mock_dry.assert_called_once_with("udp_flood", {"rate": 50})
            mock_live.assert_not_called()
            assert result["success"] is True

    def test_execute_skill_live_calls_correct_function(self):
        """live 模式应调用 execute_skill_live。"""
        from src.pktgen.adapter import _execute_skill

        with patch("src.pktgen.adapter.is_dry_run", return_value=False), \
             patch("src.pktgen.adapter.get_pktgen_host", return_value="10.0.0.1"), \
             patch("src.pktgen.adapter.get_pktgen_port", return_value=9999), \
             patch("src.pktgen.adapter._import_pktgen") as mock_import:
            mock_dry = MagicMock()
            mock_live = MagicMock(return_value={"success": True, "mode": "live"})
            mock_import.return_value = (mock_dry, mock_live)

            result = _execute_skill("udp_flood", {"rate": 50})

            mock_dry.assert_not_called()
            mock_live.assert_called_once_with(
                "udp_flood", {"rate": 50}, host="10.0.0.1", port=9999
            )
            assert result["success"] is True

    def test_none_params_stripped(self):
        """None 值参数应被剔除，让 Pktgen 使用自己的默认值。"""
        from src.pktgen.adapter import _execute_skill

        with patch("src.pktgen.adapter.is_dry_run", return_value=True), \
             patch("src.pktgen.adapter._import_pktgen") as mock_import:
            mock_dry = MagicMock(return_value={"success": True})
            mock_import.return_value = (mock_dry, MagicMock())

            _execute_skill("udp_flood", {"rate": 50, "dport": None, "sport": None})

            call_params = mock_dry.call_args[0][1]
            assert "dport" not in call_params
            assert "sport" not in call_params
            assert "rate" in call_params


class TestWaitForAttack:
    """_wait_for_attack 同步等待测试。"""

    def test_sleeps_for_duration_in_live_mode(self):
        """live 模式下应 sleep duration_ms / 1000 秒。"""
        from src.pktgen.adapter import _wait_for_attack
        import time

        with patch("time.sleep") as mock_sleep:
            _wait_for_attack({"duration": 3000})
            mock_sleep.assert_called_once_with(3.0)

    def test_no_sleep_when_duration_zero(self):
        """duration=0 时不 sleep。"""
        from src.pktgen.adapter import _wait_for_attack
        import time

        with patch("time.sleep") as mock_sleep:
            _wait_for_attack({"duration": 0})
            mock_sleep.assert_not_called()

    def test_no_sleep_when_duration_missing(self):
        """没有 duration 参数时不 sleep。"""
        from src.pktgen.adapter import _wait_for_attack
        import time

        with patch("time.sleep") as mock_sleep:
            _wait_for_attack({})
            mock_sleep.assert_not_called()

    def test_sleep_capped_at_60s(self):
        """duration 超过 60000ms 时，sleep 最多 60 秒。"""
        from src.pktgen.adapter import _wait_for_attack
        import time

        with patch("time.sleep") as mock_sleep:
            _wait_for_attack({"duration": 120000})
            mock_sleep.assert_called_once_with(60.0)


class TestEnvVarDefaults:
    """工具从环境变量读取默认值测试。"""

    def test_traffic_send_reads_env_duration(self):
        """traffic_send 应从 ATK_DURATION_S 读取默认 duration。"""
        import os
        os.environ["ATK_DURATION_S"] = "8"
        os.environ["ATK_PPS"] = "200"
        try:
            from src.agent.tools import traffic_send
            # 不传 duration_s，应使用 env var
            with patch("src.agent.tools.traffic_send_tool") as mock_send, \
                 patch("src.agent.tools.interrupt", return_value=True):
                mock_send.return_value = {"success": True}
                traffic_send.invoke({
                    "dst_ip": "10.99.80.160", "dst_port": 8080,
                })
                call_args = mock_send.call_args
                assert call_args[1]["duration_s"] == 8
                assert call_args[1]["pps"] == 200
        finally:
            os.environ.pop("ATK_DURATION_S", None)
            os.environ.pop("ATK_PPS", None)

    def test_mixed_traffic_send_reads_env_duration(self):
        """mixed_traffic_send 应从 ATK_DURATION_S 读取默认 duration。"""
        import os
        os.environ["ATK_DURATION_S"] = "7"
        os.environ["ATK_PPS"] = "150"
        try:
            from src.agent.tools import mixed_traffic_send
            with patch("src.agent.tools.mixed_traffic_send_tool") as mock_send, \
                 patch("src.agent.tools.interrupt", return_value=True):
                mock_send.return_value = {"success": True}
                mixed_traffic_send.invoke({
                    "dst_ip": "10.99.80.160",
                    "traffic_spec_json": '[{"stream_id":"s1","protocol_stack":["IP","UDP"],"fields":{},"percentage":100}]',
                })
                call_args = mock_send.call_args
                assert call_args[1]["duration_s"] == 7
                assert call_args[1]["pps"] == 150
        finally:
            os.environ.pop("ATK_DURATION_S", None)
            os.environ.pop("ATK_PPS", None)


class TestRttSampling:
    """RTT 采样附加测试。"""

    def test_rtt_attached_when_monitor_running(self):
        """PingMonitor 运行时，RTT 采样应附加到结果中。"""
        from src.pktgen.adapter import _sample_rtt
        import time

        mock_monitor = MagicMock()
        mock_monitor.is_running.return_value = True
        mock_monitor.get_samples_since.return_value = [
            {"ts": time.time(), "rtt_ms": 10.0, "sent": 1, "received": 1},
            {"ts": time.time(), "rtt_ms": 20.0, "sent": 1, "received": 1},
        ]

        with patch("src.pktgen.adapter.get_ping_monitor", return_value=mock_monitor):
            result = _sample_rtt({"success": True}, time.time())

        assert "rtt_during" in result
        assert result["rtt_during"]["avg_rtt_ms"] == 15.0
        assert result["rtt_during"]["min_rtt_ms"] == 10.0
        assert result["rtt_during"]["max_rtt_ms"] == 20.0
        assert len(result["rtt_during"]["samples"]) == 2
        # 新增：攻击窗口与观测窗口时间点应被暴露
        assert "attack_window" in result
        assert "start" in result["attack_window"] and "end" in result["attack_window"]
        assert result["attack_window"]["mode"] in {"dry_run", "live"}
        assert "observation_window" in result
        assert result["observation_window"]["sample_count"] == 2

    def test_rtt_null_when_monitor_not_running(self):
        """PingMonitor 未运行时，rtt_during 应为 None。"""
        from src.pktgen.adapter import _sample_rtt
        import time

        mock_monitor = MagicMock()
        mock_monitor.is_running.return_value = False

        with patch("src.pktgen.adapter.get_ping_monitor", return_value=mock_monitor):
            result = _sample_rtt({"success": True}, time.time())

        assert result["rtt_during"] is None

    def test_rtt_null_when_no_samples(self):
        """PingMonitor 运行但无样本时，rtt_during 应为 None。"""
        from src.pktgen.adapter import _sample_rtt
        import time

        mock_monitor = MagicMock()
        mock_monitor.is_running.return_value = True
        mock_monitor.get_samples_since.return_value = []

        with patch("src.pktgen.adapter.get_ping_monitor", return_value=mock_monitor):
            result = _sample_rtt({"success": True}, time.time())

        assert result["rtt_during"] is None

    def test_rtt_on_exception_returns_null(self):
        """RTT 采样异常时不应中断，应返回 None。"""
        from src.pktgen.adapter import _sample_rtt
        import time

        with patch("src.pktgen.adapter.get_ping_monitor", side_effect=RuntimeError("boom")):
            result = _sample_rtt({"success": True}, time.time())

        assert result["rtt_during"] is None


class TestPacketSequenceJsonParsing:
    """pktgen_packet_sequence 的 JSON 解析测试。"""

    def test_valid_json_parsed_to_list(self):
        """有效的 JSON 字符串应被解析为 Python list。"""
        from src.pktgen.adapter import pktgen_packet_sequence

        seq_json = json.dumps([{
            "eth_dst_addr": "00:11:44:55:66:77",
            "eth_src_addr": "00:11:12:34:56:78",
            "ip_dst_addr": ALLOWLISTED_IP,
            "ip_src_addr": "192.168.1.1/24",
            "sport": 9, "dport": 10,
            "ethType": "ipv4", "ipProto": "udp",
            "vlanid": 1, "pktSize": 128,
        }])

        with patch("src.pktgen.adapter._execute_skill") as mock_exec, \
             patch("src.pktgen.adapter._hitl_gate", return_value=True), \
             patch("src.pktgen.adapter.validate_target"):
            mock_exec.return_value = {"success": True}

            pktgen_packet_sequence.invoke({
                "dst_ip": ALLOWLISTED_IP, "sequences": seq_json, "rate": 50,
            })

            # _execute_skill(name, params) — positional args
            _, params = mock_exec.call_args[0]
            sequences = params["sequences"]
            assert isinstance(sequences, list)
            assert sequences[0]["ip_dst_addr"] == ALLOWLISTED_IP

    def test_invalid_json_returns_error(self):
        """无效的 JSON 字符串应返回错误，不抛异常。"""
        from src.pktgen.adapter import pktgen_packet_sequence

        with patch("src.pktgen.adapter.validate_target"):
            result = pktgen_packet_sequence.invoke({
                "dst_ip": ALLOWLISTED_IP, "sequences": "not valid json {{{",
            })

            assert result["success"] is False
            assert "Invalid JSON" in result["error"]

    def test_auto_fills_missing_eth_dst_addr(self):
        """缺失或全零的 eth_dst_addr 应被自动填充为 topology.yaml 的 dst_mac。"""
        from src.pktgen.adapter import pktgen_packet_sequence

        seq_json = json.dumps([{
            "eth_dst_addr": "00:00:00:00:00:01",
            "eth_src_addr": "00:00:00:00:00:02",
            "ip_dst_addr": ALLOWLISTED_IP,
            "ip_src_addr": "10.0.0.1",
            "sport": 0, "dport": 0,
            "ethType": "0x0800", "ipProto": 1,
            "vlanid": 0, "pktSize": 64,
        }])

        with patch("src.pktgen.adapter._execute_skill") as mock_exec, \
             patch("src.pktgen.adapter._hitl_gate", return_value=True), \
             patch("src.pktgen.adapter.validate_target"), \
             patch("src.pktgen.adapter._get_dst_mac", return_value="f0:c4:78:4c:a5:55"):
            mock_exec.return_value = {"success": True}

            pktgen_packet_sequence.invoke({
                "dst_ip": ALLOWLISTED_IP, "sequences": seq_json, "rate": 50,
            })

            _, params = mock_exec.call_args[0]
            sequences = params["sequences"]
            # LLM 编造的 00:00:00:00:00:01 (all-zeros pattern) 应被替换
            assert sequences[0]["eth_dst_addr"] == "f0:c4:78:4c:a5:55"


class TestRunTrafficToolIntegration:
    """_run_traffic_tool 集成流程测试。"""

    def test_full_live_flow_calls_all_steps(self):
        """live 模式完整流程：allowlist → HITL → execute → RTT。"""
        from src.pktgen.adapter import _run_traffic_tool

        with patch("src.pktgen.adapter.is_dry_run", return_value=False), \
             patch("src.pktgen.adapter.validate_target") as mock_val, \
             patch("src.pktgen.adapter.interrupt", return_value=True) as mock_int, \
             patch("src.pktgen.adapter._import_pktgen") as mock_imp, \
             patch("src.pktgen.adapter.get_ping_monitor") as mock_pm:
            mock_exec = MagicMock(return_value={"success": True, "mode": "live"})
            mock_imp.return_value = (MagicMock(), mock_exec)

            mock_monitor = MagicMock()
            mock_monitor.is_running.return_value = True
            mock_monitor.get_samples_since.return_value = [{"ts": 1.0, "rtt_ms": 30.0, "sent": 1, "received": 1}]
            mock_pm.return_value = mock_monitor

            result = _run_traffic_tool(
                "udp_flood",
                {"dst_ip": ALLOWLISTED_IP, "rate": 50},
                dst_ip=ALLOWLISTED_IP,
            )

            mock_val.assert_called_once_with(ALLOWLISTED_IP)
            mock_int.assert_called_once()
            mock_exec.assert_called_once()
            assert result["success"] is True
            assert "rtt_during" in result
            assert result["rtt_during"]["avg_rtt_ms"] == 30.0
            # 新增：live 模式下 attack_window.mode 应为 live
            assert result["attack_window"]["mode"] == "live"
            assert "observation_window" in result

    def test_dry_run_skips_hitl_and_still_executes(self):
        """dry-run 模式跳过 HITL，但仍执行 and 附加 RTT。"""
        from src.pktgen.adapter import _run_traffic_tool

        with patch("src.pktgen.adapter.is_dry_run", return_value=True), \
             patch("src.pktgen.adapter.validate_target") as mock_val, \
             patch("src.pktgen.adapter.interrupt") as mock_int, \
             patch("src.pktgen.adapter._import_pktgen") as mock_imp, \
             patch("src.pktgen.adapter.get_ping_monitor") as mock_pm:
            mock_exec = MagicMock(return_value={"success": True, "mode": "dry_run"})
            mock_imp.return_value = (mock_exec, MagicMock())

            mock_monitor = MagicMock()
            mock_monitor.is_running.return_value = False
            mock_pm.return_value = mock_monitor

            result = _run_traffic_tool(
                "udp_flood", {"rate": 50}, dst_ip=ALLOWLISTED_IP,
            )

            mock_val.assert_called_once()
            mock_int.assert_not_called()  # dry-run 跳过 HITL
            mock_exec.assert_called_once()
            assert result["success"] is True

    def test_non_traffic_skill_skips_hitl_and_allowlist(self):
        """非流量技能（如 stats_monitoring）不触发 allowlist + HITL。"""
        from src.pktgen.adapter import _run_traffic_tool

        with patch("src.pktgen.adapter.is_dry_run", return_value=False), \
             patch("src.pktgen.adapter.validate_target") as mock_val, \
             patch("src.pktgen.adapter.interrupt") as mock_int, \
             patch("src.pktgen.adapter._import_pktgen") as mock_imp:
            mock_exec = MagicMock(return_value={"success": True})
            mock_imp.return_value = (MagicMock(), mock_exec)

            # stats_monitoring is NOT in _SKILLS_WITH_HITL or _SKILLS_WITH_DST_IP
            result = _run_traffic_tool("stats_monitoring", {"interval_ms": 1000})

            mock_val.assert_not_called()
            mock_int.assert_not_called()
            mock_exec.assert_called_once()
            assert result["success"] is True
