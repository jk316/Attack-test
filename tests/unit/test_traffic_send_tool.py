"""Tests for traffic_send_tool - RED stage"""
import re
from unittest.mock import patch, MagicMock, call
import pytest

# IP that exists in the actual allowlist (src/config/allowlist.json)
ALLOWLISTED_IP = "10.99.80.160"


class TestTrafficSendTool:
    """Test suite for traffic_send_tool"""

    # ── Allowlist / Target Validation ──────────────────────────

    def test_non_allowlist_ip_rejected(self):
        """非 allowlist IP 必须被拒绝"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with pytest.raises(ValueError, match="not in allowlist"):
            traffic_send_tool("192.168.1.99", dst_port=8080, pps=10)

    def test_allowlist_ip_accepted(self):
        """allowlist IP 应被接受并尝试发送"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with patch("src.tools.traffic_send_tool.send"), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                duration_s=1, pps=10, packet_size=64, flow_count=1
            )
        assert result["success"] is True
        assert result["errors"] == []

    def test_broadcast_ip_rejected(self):
        """广播地址应被拒绝"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with pytest.raises(ValueError, match="(?i)broadcast"):
            traffic_send_tool("192.168.1.255", dst_port=8080)

    def test_multicast_ip_rejected(self):
        """多播地址应被拒绝"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with pytest.raises(ValueError, match="(?i)multicast"):
            traffic_send_tool("224.0.0.1", dst_port=8080)

    def test_empty_allowlist_rejects(self):
        """空 allowlist 应拒绝所有 IP"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with patch("src.tools.ping_rtt_tool.ALLOWLIST", []):
            with pytest.raises(ValueError, match="allowlist is empty"):
                traffic_send_tool("192.168.1.1", dst_port=8080, pps=10)

    # ── Parameter Upper Limits ─────────────────────────────────

    def test_pps_exceeds_max_rejected(self):
        """pps > 200 必须拒绝"""
        from src.tools.traffic_send_tool import traffic_send_tool, MAX_PPS

        with pytest.raises(ValueError, match="(?i)pps.*exceeds"):
            traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                pps=MAX_PPS + 1
            )

    def test_duration_exceeds_max_rejected(self):
        """duration_s > 10 必须拒绝"""
        from src.tools.traffic_send_tool import traffic_send_tool, MAX_DURATION_S

        with pytest.raises(ValueError, match="(?i)duration.*exceeds"):
            traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                duration_s=MAX_DURATION_S + 1, pps=10
            )

    def test_packet_size_exceeds_max_rejected(self):
        """packet_size > 512 必须拒绝"""
        from src.tools.traffic_send_tool import traffic_send_tool, MAX_PACKET_SIZE

        with pytest.raises(ValueError, match="(?i)packet_size.*exceeds"):
            traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                packet_size=MAX_PACKET_SIZE + 1, pps=10
            )

    def test_flow_count_exceeds_max_rejected(self):
        """flow_count > 50 必须拒绝"""
        from src.tools.traffic_send_tool import traffic_send_tool, MAX_FLOW_COUNT

        with pytest.raises(ValueError, match="(?i)flow_count.*exceeds"):
            traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                flow_count=MAX_FLOW_COUNT + 1, pps=10
            )

    def test_iat_jitter_exceeds_max_rejected(self):
        """iat_jitter_ms > 20 必须拒绝"""
        from src.tools.traffic_send_tool import traffic_send_tool, MAX_IAT_JITTER_MS

        with pytest.raises(ValueError, match="(?i)iat_jitter_ms.*exceeds"):
            traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                iat_jitter_ms=MAX_IAT_JITTER_MS + 1, pps=10
            )

    # ── Security Hard Constraints ──────────────────────────────

    def test_src_ip_forgery_rejected(self):
        """不允许伪造 src_ip"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with pytest.raises(ValueError, match="(?i)src_ip.*not allowed"):
            traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                src_ip="1.2.3.4", pps=10
            )

    def test_invalid_dst_port_rejected(self):
        """无效端口应被拒绝"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with pytest.raises(ValueError, match="(?i)port"):
            traffic_send_tool(ALLOWLISTED_IP, dst_port=99999, pps=10)

    # ── Output Format ─────────────────────────────────────────

    def test_output_structure_on_success(self):
        """成功时输出应包含必需字段"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with patch("src.tools.traffic_send_tool.send"), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                duration_s=1, pps=10, packet_size=64, flow_count=2,
                iat_jitter_ms=5
            )

        assert "success" in result
        assert result["success"] is True
        assert "params" in result
        assert "packets_sent" in result
        assert "elapsed_s" in result
        assert "effective_pps" in result
        assert "errors" in result

    def test_output_structure_on_validation_failure(self):
        """校验失败时应抛出 ValueError"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with pytest.raises(ValueError):
            traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                pps=201
            )

    def test_params_echoed_in_output(self):
        """输出应回显输入参数"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with patch("src.tools.traffic_send_tool.send"), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                duration_s=3, pps=50, packet_size=128, flow_count=3,
                iat_jitter_ms=10
            )

        params = result["params"]
        assert params["dst_ip"] == ALLOWLISTED_IP
        assert params["dst_port"] == 8080
        assert params["duration_s"] == 3
        assert params["pps"] == 50
        assert params["packet_size"] == 128
        assert params["flow_count"] == 3
        assert params["iat_jitter_ms"] == 10

    def test_packets_sent_per_flow_tracking(self):
        """应统计每个 flow 的发送包数"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with patch("src.tools.traffic_send_tool.send"), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                duration_s=1, pps=10, packet_size=64, flow_count=3
            )

        packets_sent = result["packets_sent"]
        assert "total" in packets_sent
        assert "per_flow" in packets_sent
        assert isinstance(packets_sent["total"], int)
        assert isinstance(packets_sent["per_flow"], dict)

    def test_effective_pps_is_reasonable(self):
        """有效 pps 应 >= 0"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with patch("src.tools.traffic_send_tool.send"), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                duration_s=1, pps=100, packet_size=64, flow_count=1
            )

        assert isinstance(result["effective_pps"], (int, float))
        assert result["effective_pps"] >= 0

    def test_scapy_not_available_error(self):
        """Scapy 不可用时应抛出 ImportError"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with patch("src.tools.traffic_send_tool.HAS_SCAPY", False):
            with pytest.raises(ImportError, match="(?i)scapy"):
                traffic_send_tool(
                    ALLOWLISTED_IP, dst_port=8080,
                    duration_s=1, pps=10
                )
