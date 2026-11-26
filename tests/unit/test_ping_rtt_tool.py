"""Tests for ping_rtt_tool - RED stage"""
import json
import subprocess
from unittest.mock import patch, MagicMock
import pytest

# IP that exists in the actual allowlist (allowlist.json)
ALLOWLISTED_IP = "10.99.80.160"


class TestPingRttTool:
    """Test suite for ping_rtt_tool"""

    def test_allowlist_check_rejects_non_allowlist_ip(self):
        """非 allowlist IP 必须被拒绝（契约 §4：success:false + 校验错误，不探测）"""
        from src.tools.ping_rtt_tool import ping_rtt_tool

        with patch('subprocess.run') as mock_run:
            result = ping_rtt_tool("192.168.1.99", count=4)
        assert result["success"] is False
        assert "not in allowlist" in result["error"]
        mock_run.assert_not_called()  # 不执行探测

    def test_allowlist_check_accepts_allowlist_ip(self):
        """allowlist IP 应该被接受（模拟执行）"""
        from src.tools.ping_rtt_tool import ping_rtt_tool

        mock_output = (
            f"PING {ALLOWLISTED_IP}: 56 data bytes, timeout 2s\n"
            f"64 bytes from {ALLOWLISTED_IP}: icmp_seq=0 ttl=64 time=1.234 ms\n"
            f"64 bytes from {ALLOWLISTED_IP}: icmp_seq=1 ttl=64 time=1.456 ms\n\n"
            f"--- {ALLOWLISTED_IP} ping statistics ---\n"
            "2 packets transmitted, 2 packets received, 0% packet loss\n"
            "round-trip min/avg/max = 1.234/1.345/1.456 ms"
        )

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=mock_output,
                stderr=""
            )
            result = ping_rtt_tool(ALLOWLISTED_IP, count=2)
            assert result["success"] is True

    def test_output_json_structure(self):
        """输出必须是结构化 JSON 包含 avg_rtt_ms 和 loss_pct"""
        from src.tools.ping_rtt_tool import ping_rtt_tool

        mock_output = (
            f"PING {ALLOWLISTED_IP}: 56 data bytes, timeout 2s\n"
            f"64 bytes from {ALLOWLISTED_IP}: icmp_seq=0 ttl=64 time=1.234 ms\n\n"
            f"--- {ALLOWLISTED_IP} ping statistics ---\n"
            "1 packets transmitted, 1 packets received, 0% packet loss\n"
            "round-trip min/avg/max = 1.234/1.234/1.234 ms"
        )

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=mock_output,
                stderr=""
            )
            result = ping_rtt_tool(ALLOWLISTED_IP, count=1)

        assert "avg_rtt_ms" in result
        assert "loss_pct" in result
        assert isinstance(result["avg_rtt_ms"], float)
        assert isinstance(result["loss_pct"], (int, float))

    def test_loss_100_when_all_packets_lost(self):
        """全部丢包时 loss_pct 应为 100"""
        from src.tools.ping_rtt_tool import ping_rtt_tool

        mock_output = (
            f"PING {ALLOWLISTED_IP}: 56 data bytes, timeout 2s\n\n"
            f"--- {ALLOWLISTED_IP} ping statistics ---\n"
            "2 packets transmitted, 0 packets received, 100% packet loss"
        )

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=mock_output,
                stderr=""
            )
            result = ping_rtt_tool(ALLOWLISTED_IP, count=2)

        assert result["loss_pct"] == 100.0

    def test_handles_empty_allowlist(self):
        """空 allowlist 应拒绝所有 IP（契约 §4 拒绝形状）"""
        from src.tools.ping_rtt_tool import ping_rtt_tool

        with patch('src.tools.ping_rtt_tool.ALLOWLIST', []):
            result = ping_rtt_tool("192.168.1.1", count=1)
        assert result["success"] is False
        assert "allowlist is empty" in result["error"]

    def test_count_parameter_passed_to_ping(self):
        """count 参数必须传递给 ping 命令"""
        from src.tools.ping_rtt_tool import ping_rtt_tool
        import sys

        mock_output = (
            f"PING {ALLOWLISTED_IP}: 56 data bytes\n"
            f"--- {ALLOWLISTED_IP} ping statistics ---\n"
            "1 packets transmitted, 1 packets received, 0% packet loss\n"
            "round-trip min/avg/max = 1.0/1.0/1.0 ms"
        )

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")
            ping_rtt_tool(ALLOWLISTED_IP, count=5)

            call_args = mock_run.call_args
            flag = "-n" if sys.platform == "win32" else "-c"
            assert flag in call_args[0][0]
            assert "5" in call_args[0][0]

    def test_error_handling_on_ping_failure(self):
        """ping 执行失败时应返回错误信息"""
        from src.tools.ping_rtt_tool import ping_rtt_tool

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("ping", 10)
            result = ping_rtt_tool(ALLOWLISTED_IP, count=1)

        assert result["success"] is False
        assert "error" in result

    def test_invalid_ip_format_rejected(self):
        """无效 IP 格式应被拒绝（契约 §4 拒绝形状）"""
        from src.tools.ping_rtt_tool import ping_rtt_tool

        result = ping_rtt_tool("invalid-ip", count=1)
        assert result["success"] is False
        assert "Invalid IP format" in result["error"]

    def test_broadcast_ip_rejected(self):
        """广播地址应该被拒绝（契约 §4 拒绝形状）"""
        from src.tools.ping_rtt_tool import ping_rtt_tool

        result = ping_rtt_tool("192.168.1.255", count=1)
        assert result["success"] is False
        assert "Broadcast" in result["error"]

    def test_multicast_ip_rejected(self):
        """多播地址应该被拒绝（契约 §4 拒绝形状）"""
        from src.tools.ping_rtt_tool import ping_rtt_tool

        result = ping_rtt_tool("224.0.0.1", count=1)
        assert result["success"] is False
        assert "Multicast" in result["error"]

class TestPingCommandBuilding:
    """T005：build_ping_cmd 跨平台参数断言（不硬编码 OS）。"""

    def test_build_ping_cmd_unix(self, monkeypatch):
        import sys

        from src.tools.ping_rtt_tool import build_ping_cmd

        monkeypatch.setattr(sys, "platform", "linux")
        assert build_ping_cmd("10.99.80.160", 4, 10) == [
            "ping", "-c", "4", "-W", "10", "10.99.80.160",
        ]

    def test_build_ping_cmd_windows(self, monkeypatch):
        import sys

        from src.tools.ping_rtt_tool import build_ping_cmd

        monkeypatch.setattr(sys, "platform", "win32")
        assert build_ping_cmd("10.99.80.160", 3, 2) == [
            "ping", "-n", "3", "-w", "2000", "10.99.80.160",
        ]


class TestPingErrorPaths:
    """T005：命令缺失 / 超时 / 全丢包路径（契约 contracts/tool-result-json.md §4）。"""

    def test_command_not_found(self):
        from src.tools.ping_rtt_tool import ping_rtt_tool

        with patch('subprocess.run', side_effect=FileNotFoundError("ping")):
            result = ping_rtt_tool(ALLOWLISTED_IP, count=1)

        assert result["success"] is False
        assert result["error"] == "ping command not found"
        assert result["loss_pct"] == 100.0

    def test_timeout_expired(self):
        from src.tools.ping_rtt_tool import ping_rtt_tool

        with patch('subprocess.run',
                   side_effect=subprocess.TimeoutExpired("ping", 10)):
            result = ping_rtt_tool(ALLOWLISTED_IP, count=1)

        assert result["success"] is False
        assert result["error"] == "Ping timeout expired"
        assert result["loss_pct"] == 100.0

    def test_all_lost_reports_inf_avg_and_100_loss(self):
        """全丢包 → avg_rtt_ms=inf 且 loss_pct=100（契约 §4）。"""
        from src.tools.ping_rtt_tool import ping_rtt_tool

        mock_output = (
            f"PING {ALLOWLISTED_IP}: 56 data bytes, timeout 2s\n\n"
            f"--- {ALLOWLISTED_IP} ping statistics ---\n"
            "2 packets transmitted, 0 packets received, 100% packet loss"
        )

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=mock_output, stderr="",
            )
            result = ping_rtt_tool(ALLOWLISTED_IP, count=2)

        assert result["success"] is True
        assert result["avg_rtt_ms"] == float('inf')
        assert result["loss_pct"] == 100.0


class TestRejectionDualEntry:
    """T015：拒绝路径双入口（G-007、SC-005）。

    ping_rtt_tool 与 PingMonitor.start 对非 allowlist/广播/组播/非法格式
    均拒绝，且不构造/启动任何探测进程。
    """

    REJECT_CASES = [
        ("192.168.1.99", "not in allowlist"),
        ("192.168.1.255", "Broadcast"),
        ("224.0.0.1", "Multicast"),
        ("999.1.1.1", "Invalid IP format"),
    ]

    def test_ping_rtt_tool_rejects_without_probe(self):
        from src.tools.ping_rtt_tool import ping_rtt_tool

        for ip, reason in self.REJECT_CASES:
            with patch('subprocess.run') as mock_run:
                result = ping_rtt_tool(ip, count=1)
            assert result["success"] is False, ip
            assert reason in result["error"], ip
            mock_run.assert_not_called()  # 零探测

    def test_monitor_start_rejects_without_process(self):
        from src.tools.ping_monitor import PingMonitor

        for ip, reason in self.REJECT_CASES:
            m = PingMonitor()
            with patch("src.tools.ping_monitor.subprocess.Popen") as mock_popen:
                with pytest.raises(ValueError, match=reason):
                    m.start(ip)
            mock_popen.assert_not_called()  # 未构造探测进程


class TestStatsSectionParsing:
    """T016：全丢与跨平台统计段解析（Unix/Windows 两种格式）。"""

    def test_unix_stats_section(self):
        from src.tools.ping_rtt_tool import parse_ping_output

        output = (
            "3 packets transmitted, 2 packets received, 33% packet loss\n"
            "round-trip min/avg/max = 1.0/2.5/4.0 ms"
        )
        r = parse_ping_output(output)
        assert r["success"] is True
        assert r["packets_transmitted"] == 3
        assert r["packets_received"] == 2
        assert r["loss_pct"] == 33.0
        assert r["avg_rtt_ms"] == 2.5

    def test_windows_stats_section(self):
        from src.tools.ping_rtt_tool import parse_ping_output

        output = (
            "    Packets: Sent = 4, Received = 3, Lost = 1 (25% loss),\n"
            "Approximate round trip times in milli-seconds:\n"
            "    Minimum = 2ms, Maximum = 10ms, Average = 6ms"
        )
        r = parse_ping_output(output)
        assert r["success"] is True
        assert r["packets_transmitted"] == 4
        assert r["packets_received"] == 3
        assert r["loss_pct"] == 25.0
        assert r["avg_rtt_ms"] == 6.0

    def test_unix_full_loss(self):
        from src.tools.ping_rtt_tool import parse_ping_output

        output = "3 packets transmitted, 0 packets received, 100% packet loss"
        r = parse_ping_output(output)
        assert r["success"] is True
        assert r["avg_rtt_ms"] == float('inf')
        assert r["loss_pct"] == 100.0

    def test_windows_full_loss(self):
        from src.tools.ping_rtt_tool import parse_ping_output

        output = (
            "    Packets: Sent = 4, Received = 0, Lost = 4 (100% loss),"
        )
        r = parse_ping_output(output)
        assert r["success"] is True
        assert r["avg_rtt_ms"] == float('inf')
        assert r["loss_pct"] == 100.0
