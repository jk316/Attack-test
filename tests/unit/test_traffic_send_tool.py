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


class TestRawSocketSend:
    """Tests for the raw socket fast path and fallback logic."""

    def test_raw_socket_path_used_when_available(self):
        """裸 socket 可用时应走快速路径，不调用 Scapy send()。"""
        from src.tools.traffic_send_tool import traffic_send_tool

        mock_sock = MagicMock()
        with patch("src.tools.traffic_send_tool._create_raw_socket", return_value=mock_sock), \
             patch("src.tools.traffic_send_tool.send") as mock_send, \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                duration_s=1, pps=20, packet_size=64, flow_count=2,
            )

        # raw socket should be used
        assert mock_sock.sendto.called
        # Scapy send should NOT be called
        mock_send.assert_not_called()
        # return value should indicate raw socket was used
        assert result["send_mode"] == "raw"
        mock_sock.close.assert_called_once()

    def test_fallback_to_scapy_when_all_sockets_fail(self):
        """裸 socket 和 UDP socket 都不可用时应回退到 Scapy send()。"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with patch("src.tools.traffic_send_tool._create_raw_socket", return_value=None), \
             patch("src.tools.traffic_send_tool._create_udp_sockets", return_value=None), \
             patch("src.tools.traffic_send_tool.send") as mock_send, \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                duration_s=1, pps=20, packet_size=64, flow_count=1,
            )

        # Scapy send should be used
        assert mock_send.called
        assert result["send_mode"] == "scapy"

    def test_prebuilt_packets_count_matches_flow_count(self):
        """预构建包数量应等于 flow_count。"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with patch("src.tools.traffic_send_tool._create_raw_socket", return_value=MagicMock()), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                duration_s=1, pps=20, packet_size=64, flow_count=5,
            )

        # flow_count=5 should produce 5 per_flow entries
        per_flow = result["packets_sent"]["per_flow"]
        assert len(per_flow) == 5
        assert all(k in per_flow for k in [0, 1, 2, 3, 4])

    def test_prebuilt_sports_are_unique(self):
        """每个预构建包应有不同的 sport（1024 + flow_id）。"""
        from src.tools.traffic_send_tool import traffic_send_tool

        # Capture the bytes sent via raw socket
        sent_data: list[bytes] = []
        mock_sock = MagicMock()

        def _capture_sendto(data, addr):
            sent_data.append(data)

        mock_sock.sendto.side_effect = _capture_sendto

        with patch("src.tools.traffic_send_tool._create_raw_socket", return_value=mock_sock), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                duration_s=1, pps=100, packet_size=64, flow_count=3,
            )

        assert len(sent_data) > 0
        # First 3 packets should be from flow 0, 1, 2 (round-robin)
        # Each should contain the correct sport in the UDP header bytes
        sports_found = set()
        for data in sent_data[:3]:
            # UDP header: bytes 0-1=sport, 2-3=dport, 4-5=length, 6-7=checksum
            # In the full IP packet, UDP starts at offset 20 (IP header)
            udp_sport = int.from_bytes(data[20:22], "big")
            sports_found.add(udp_sport)

        assert len(sports_found) >= 2  # at least 2 different sports used

    def test_create_raw_socket_returns_none_on_permission_error(self):
        """权限不足时 _create_raw_socket 返回 None。"""
        from src.tools.traffic_send_tool import _create_raw_socket

        with patch("socket.socket", side_effect=PermissionError("denied")):
            result = _create_raw_socket()
        assert result is None

    def test_create_raw_socket_returns_socket_on_success(self):
        """正常情况 _create_raw_socket 返回 socket 对象。"""
        from src.tools.traffic_send_tool import _create_raw_socket

        mock_sock = MagicMock()
        with patch("socket.socket", return_value=mock_sock):
            result = _create_raw_socket()
        assert result is mock_sock
        mock_sock.setsockopt.assert_called_once()
