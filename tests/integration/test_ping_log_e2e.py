"""Integration tests for ping parsing + JSONL logging (T021 / SC-007/008).

mock subprocess 输出 Unix 与 Windows 两种 ping 格式断言解析结果；
log_tool 两次追加后逐行 json.loads 可解析且含 timestamp。No real ping
subprocess, no real network — subprocess.run is mocked.
"""
import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

ALLOWLISTED_IP = "10.99.80.160"


class TestPingOutputParsing:
    def test_unix_format_parsed(self):
        from src.tools.ping_rtt_tool import parse_ping_output

        output = (
            f"PING {ALLOWLISTED_IP}: 56 data bytes\n"
            f"64 bytes from {ALLOWLISTED_IP}: icmp_seq=0 ttl=64 time=1.2 ms\n"
            f"64 bytes from {ALLOWLISTED_IP}: icmp_seq=1 ttl=64 time=1.8 ms\n\n"
            f"--- {ALLOWLISTED_IP} ping statistics ---\n"
            "2 packets transmitted, 2 packets received, 0% packet loss\n"
            "round-trip min/avg/max = 1.200/1.500/1.800 ms"
        )
        result = parse_ping_output(output)
        assert result["success"] is True
        assert result["avg_rtt_ms"] == 1.5
        assert result["loss_pct"] == 0.0
        assert result["packets_transmitted"] == 2
        assert result["packets_received"] == 2

    def test_windows_format_parsed(self):
        from src.tools.ping_rtt_tool import parse_ping_output

        output = (
            f"Pinging {ALLOWLISTED_IP} with 32 bytes of data:\n"
            f"Reply from {ALLOWLISTED_IP}: bytes=32 time=3ms TTL=64\n"
            f"Reply from {ALLOWLISTED_IP}: bytes=32 time=7ms TTL=64\n\n"
            f"Ping statistics for {ALLOWLISTED_IP}:\n"
            "    Packets: Sent = 2, Received = 2, Lost = 0 (0% loss),\n"
            "Approximate round trip times in milli-seconds:\n"
            "    Minimum = 3ms, Maximum = 7ms, Average = 5ms"
        )
        result = parse_ping_output(output)
        assert result["success"] is True
        assert result["avg_rtt_ms"] == 5.0
        assert result["loss_pct"] == 0.0
        assert result["packets_transmitted"] == 2
        assert result["packets_received"] == 2

    def test_unix_full_loss_inf(self):
        from src.tools.ping_rtt_tool import parse_ping_output

        output = (
            f"--- {ALLOWLISTED_IP} ping statistics ---\n"
            "2 packets transmitted, 0 packets received, 100% packet loss"
        )
        result = parse_ping_output(output)
        assert result["success"] is True
        assert result["avg_rtt_ms"] == float("inf")
        assert result["loss_pct"] == 100.0


class TestPingLogE2E:
    def test_ping_then_log_roundtrip(self, tmp_path):
        """ping（mock subprocess）→ log_tool 两次追加 → 逐行可解析含 timestamp。"""
        from src.tools.ping_rtt_tool import ping_rtt_tool
        from src.tools.log_tool import log_tool

        mock_output = (
            f"PING {ALLOWLISTED_IP}: 56 data bytes\n"
            f"64 bytes from {ALLOWLISTED_IP}: icmp_seq=0 ttl=64 time=2.0 ms\n\n"
            f"--- {ALLOWLISTED_IP} ping statistics ---\n"
            "1 packets transmitted, 1 packets received, 0% packet loss\n"
            "round-trip min/avg/max = 2.000/2.000/2.000 ms"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=mock_output, stderr="",
            )
            ping = ping_rtt_tool(ALLOWLISTED_IP, count=1)
        assert ping["avg_rtt_ms"] == 2.0

        log_path = str(tmp_path / "exp.jsonl")
        log_tool(log_path, {"iteration": 0, "params": {"pps": 10},
                            "rtt": ping["avg_rtt_ms"], "loss": ping["loss_pct"]})
        log_tool(log_path, {"iteration": 1, "params": {"pps": 20},
                            "rtt": 5.0, "loss": 1.0})

        with open(log_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f]
        assert len(lines) == 2
        assert lines[0]["iteration"] == 0
        assert lines[1]["iteration"] == 1
        for line in lines:
            assert "timestamp" in line
            assert line["timestamp"].endswith("+00:00")  # UTC ISO 8601


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
