"""Tests for ping_rtt_tool - RED stage"""
import json
import subprocess
from unittest.mock import patch, MagicMock
import pytest

# IP that exists in the actual allowlist (src/config/allowlist.json)
ALLOWLISTED_IP = "10.99.80.160"


class TestPingRttTool:
    """Test suite for ping_rtt_tool"""

    def test_allowlist_check_rejects_non_allowlist_ip(self):
        """非 allowlist IP 必须被拒绝"""
        from src.tools.ping_rtt_tool import ping_rtt_tool

        with pytest.raises(ValueError, match="not in allowlist"):
            ping_rtt_tool("192.168.1.99", count=4)

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
        """空 allowlist 应拒绝所有 IP"""
        from src.tools.ping_rtt_tool import ping_rtt_tool

        with patch('src.tools.ping_rtt_tool.ALLOWLIST', []):
            with pytest.raises(ValueError, match="allowlist is empty"):
                ping_rtt_tool("192.168.1.1", count=1)

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
        """无效 IP 格式应被拒绝"""
        from src.tools.ping_rtt_tool import ping_rtt_tool

        with pytest.raises(ValueError, match="Invalid IP format"):
            ping_rtt_tool("invalid-ip", count=1)

    def test_broadcast_ip_rejected(self):
        """广播地址应该被拒绝"""
        from src.tools.ping_rtt_tool import ping_rtt_tool

        with pytest.raises(ValueError, match="(?i)broadcast"):
            ping_rtt_tool("192.168.1.255", count=1)

    def test_multicast_ip_rejected(self):
        """多播地址应该被拒绝"""
        from src.tools.ping_rtt_tool import ping_rtt_tool

        with pytest.raises(ValueError, match="(?i)multicast"):
            ping_rtt_tool("224.0.0.1", count=1)