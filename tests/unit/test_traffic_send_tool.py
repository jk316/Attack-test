"""Tests for traffic_send_tool - RED stage"""
import re
from unittest.mock import patch, MagicMock, call
import pytest

# IP that exists in the actual allowlist (allowlist.json)
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

    # ── Parameter Clamping (not rejection) ──────────────────────

    def test_pps_exceeding_max_is_clamped(self):
        """pps 超过 MAX 应被 clamp 到上限，不报错"""
        from src.tools.traffic_send_tool import traffic_send_tool, MAX_PPS

        with patch("src.tools.traffic_send_tool.send"), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                pps=MAX_PPS + 5000, duration_s=1
            )
        assert result["params"]["pps"] == MAX_PPS

    def test_duration_exceeding_max_is_clamped(self):
        """duration_s 超过 MAX 应被 clamp 到上限"""
        from src.tools.traffic_send_tool import traffic_send_tool, MAX_DURATION_S

        with patch("src.tools.traffic_send_tool.send"), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                duration_s=MAX_DURATION_S + 10, pps=10
            )
        assert result["params"]["duration_s"] == MAX_DURATION_S

    def test_packet_size_exceeding_max_is_clamped(self):
        """packet_size 超过 MAX 应被 clamp 到上限"""
        from src.tools.traffic_send_tool import traffic_send_tool, MAX_PACKET_SIZE

        with patch("src.tools.traffic_send_tool.send"), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                packet_size=MAX_PACKET_SIZE + 512, pps=10, duration_s=1
            )
        assert result["params"]["packet_size"] == MAX_PACKET_SIZE

    def test_flow_count_exceeding_max_is_clamped(self):
        """flow_count 超过 MAX 应被 clamp 到上限"""
        from src.tools.traffic_send_tool import traffic_send_tool, MAX_FLOW_COUNT

        with patch("src.tools.traffic_send_tool.send"), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                flow_count=MAX_FLOW_COUNT + 50, pps=10, duration_s=1
            )
        assert result["params"]["flow_count"] == MAX_FLOW_COUNT

    def test_iat_jitter_exceeding_max_is_clamped(self):
        """iat_jitter_ms 超过 MAX 应被 clamp 到上限——修复 LLM 请求 40 导致崩溃"""
        from src.tools.traffic_send_tool import traffic_send_tool, MAX_IAT_JITTER_MS

        with patch("src.tools.traffic_send_tool.send"), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                iat_jitter_ms=MAX_IAT_JITTER_MS + 20,  # 40, simulating the actual LLM bug
                pps=10, duration_s=1
            )
        assert result["params"]["iat_jitter_ms"] == MAX_IAT_JITTER_MS

    def test_negative_params_still_rejected(self):
        """负数/零值参数仍应报错"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with pytest.raises(ValueError, match="pps must be > 0"):
            traffic_send_tool(ALLOWLISTED_IP, dst_port=8080, pps=0, duration_s=1)

        with pytest.raises(ValueError, match="pps must be > 0"):
            traffic_send_tool(ALLOWLISTED_IP, dst_port=8080, pps=-5, duration_s=1)

        with pytest.raises(ValueError, match="duration_s must be > 0"):
            traffic_send_tool(ALLOWLISTED_IP, dst_port=8080, pps=10, duration_s=0)

        with pytest.raises(ValueError, match="iat_jitter_ms must be >= 0"):
            traffic_send_tool(ALLOWLISTED_IP, dst_port=8080, pps=10, duration_s=1, iat_jitter_ms=-1)

    # ── Security Hard Constraints ──────────────────────────────

    def test_src_ip_allowed(self):
        """无状态协议允许伪造 src_ip，结果应回显。"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with patch("src.tools.traffic_send_tool.send"), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                src_ip="1.2.3.4", pps=10, duration_s=1
            )

        assert result["success"] is True
        assert result["params"]["src_ip"] == "1.2.3.4"

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
        """安全违规时（无效端口）应抛出 ValueError"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with pytest.raises(ValueError, match="(?i)port"):
            traffic_send_tool(
                ALLOWLISTED_IP, dst_port=99999,
                pps=10
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


class TestValidationMatrix:
    """T004：拒绝矩阵补齐（data-model「校验规则汇总」FR-002–006）。

    非正数拒绝、端口边界、非法 IP 格式——安全违规必须抛 ValueError。
    """

    def test_dst_port_zero_rejected(self):
        from src.tools.traffic_send_tool import traffic_send_tool

        with pytest.raises(ValueError, match="dst_port"):
            traffic_send_tool(ALLOWLISTED_IP, dst_port=0, pps=10)

    def test_dst_port_65536_rejected(self):
        from src.tools.traffic_send_tool import traffic_send_tool

        with pytest.raises(ValueError, match="dst_port"):
            traffic_send_tool(ALLOWLISTED_IP, dst_port=65536, pps=10)

    def test_packet_size_zero_rejected(self):
        from src.tools.traffic_send_tool import traffic_send_tool

        with pytest.raises(ValueError, match="packet_size must be > 0"):
            traffic_send_tool(ALLOWLISTED_IP, dst_port=8080, pps=10, packet_size=0)

    def test_flow_count_zero_rejected(self):
        from src.tools.traffic_send_tool import traffic_send_tool

        with pytest.raises(ValueError, match="flow_count must be > 0"):
            traffic_send_tool(ALLOWLISTED_IP, dst_port=8080, pps=10, flow_count=0)

    def test_negative_duration_rejected(self):
        from src.tools.traffic_send_tool import traffic_send_tool

        with pytest.raises(ValueError, match="duration_s must be > 0"):
            traffic_send_tool(ALLOWLISTED_IP, dst_port=8080, pps=10, duration_s=-1)

    def test_invalid_ip_format_rejected(self):
        """格式非法 IP（validate_target 矩阵）必须被拒绝。"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with pytest.raises(ValueError, match="Invalid IP format"):
            traffic_send_tool("999.1.1.1", dst_port=8080, pps=10)

    def test_clamp_matrix_boundaries_stay_within_limits(self):
        """越限钳制矩阵（与 T008 标注字段联动前先锁定钳制值本身）。

        直接调用纯函数 validate_params——避免真实发送循环时长（duration 钳制
        到 20s 会拖慢测试）。
        """
        from src.tools.traffic_send_tool import (
            validate_params,
            MAX_PPS, MAX_DURATION_S, MAX_PACKET_SIZE,
            MAX_FLOW_COUNT, MAX_IAT_JITTER_MS,
        )

        duration_s, pps, packet_size, flow_count, iat_jitter_ms = validate_params(
            ALLOWLISTED_IP, dst_port=8080,
            duration_s=999, pps=999999, packet_size=4096,
            flow_count=500, iat_jitter_ms=100, src_ip=None,
        )
        assert duration_s == MAX_DURATION_S
        assert pps == MAX_PPS
        assert packet_size == MAX_PACKET_SIZE
        assert flow_count == MAX_FLOW_COUNT
        assert iat_jitter_ms == MAX_IAT_JITTER_MS


class TestClampAnnotations:
    """T008：钳制标注（G1、002-1、FR-004、SC-001；契约 tool-result-json.md §1）。

    全部 mock 网络 I/O：raw socket 用 MagicMock（内存内），杜绝真实流量。
    """

    def test_over_limit_pps_annotated(self):
        from src.tools.traffic_send_tool import traffic_send_tool, MAX_PPS

        with patch("src.tools.traffic_send_tool._create_raw_socket",
                   return_value=MagicMock()), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080, pps=999999, duration_s=1,
            )
        assert result["params"]["pps"] == MAX_PPS
        assert result["requested_params"]["pps"] == 999999
        assert "pps" in result["clamped"]

    def test_all_compliant_clamped_empty(self):
        from src.tools.traffic_send_tool import traffic_send_tool

        with patch("src.tools.traffic_send_tool._create_raw_socket",
                   return_value=MagicMock()), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                duration_s=1, pps=10, packet_size=64, flow_count=1,
                iat_jitter_ms=0,
            )
        assert result["clamped"] == []
        assert result["requested_params"]["duration_s"] == 1
        assert result["requested_params"]["pps"] == 10
        assert result["requested_params"]["dst_port"] == 8080

    def test_multi_field_clamp_lists_all_field_names(self):
        from src.tools.traffic_send_tool import traffic_send_tool

        with patch("src.tools.traffic_send_tool._create_raw_socket",
                   return_value=MagicMock()), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                duration_s=1, pps=999999, packet_size=4096, flow_count=500,
            )
        assert {"pps", "packet_size", "flow_count"} <= set(result["clamped"])
        assert "duration_s" not in result["clamped"]  # 未越限的字段不标注
        assert result["requested_params"]["flow_count"] == 500

    def test_duration_clamp_detection_pure(self):
        """duration_s=999 → 标注 duration_s（纯比较函数，避免 20 秒真实发送）。"""
        from src.tools.traffic_send_tool import _clamped_fields

        requested = {"duration_s": 999, "pps": 10}
        actual = {"duration_s": 20, "pps": 10}
        assert _clamped_fields(requested, actual) == ["duration_s"]


class TestInterruptionAnnotation:
    """T009：截断标注（G3、002-3、FR-008；契约 tool-result-json.md §1）。"""

    def test_keyboard_interrupt_marks_incomplete(self):
        from src.tools.traffic_send_tool import traffic_send_tool

        mock_sock = MagicMock()

        def interrupt_sendto(data, addr):
            raise KeyboardInterrupt

        mock_sock.sendto.side_effect = interrupt_sendto

        with patch("src.tools.traffic_send_tool._create_raw_socket",
                   return_value=mock_sock), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080, duration_s=1, pps=10,
            )

        assert result["completed"] is False
        assert result["interrupt_reason"] == "keyboard_interrupt"
        assert result["packets_sent"]["total"] >= 1  # 已发部分保留

    def test_normal_completion_completed_true_no_reason(self):
        from src.tools.traffic_send_tool import traffic_send_tool

        with patch("src.tools.traffic_send_tool._create_raw_socket",
                   return_value=MagicMock()), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080, duration_s=1, pps=10,
            )
        assert result["completed"] is True
        assert "interrupt_reason" not in result
