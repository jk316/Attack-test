"""Integration tests for traffic_send multi-flow round-robin (T013 / FR-007 / SC-004).

Mocked network: raw socket replaced by an in-memory MagicMock that captures
packet bytes — no real packets leave the process. Verifies flow_count=N →
per_flow covers all N flows with counts balanced within 1, distinct source
ports (1024 + flow index), correct effective_pps, and send_mode in
{raw, udp, scapy}.
"""
from unittest.mock import MagicMock, patch

import pytest

ALLOWLISTED_IP = "10.99.80.160"


class TestMultiFlowRoundRobin:
    def test_five_flows_balanced_and_distinct_ports(self):
        from src.tools.traffic_send_tool import traffic_send_tool

        sent_packets: list[bytes] = []
        mock_sock = MagicMock()

        def capture(data, addr):
            sent_packets.append(data)

        mock_sock.sendto.side_effect = capture

        with patch("src.tools.traffic_send_tool._create_raw_socket",
                   return_value=mock_sock), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                duration_s=1, pps=20, flow_count=5,
            )

        # per_flow 覆盖全部 N 条流
        per_flow = result["packets_sent"]["per_flow"]
        assert set(per_flow.keys()) == {0, 1, 2, 3, 4}
        assert all(v >= 0 for v in per_flow.values())

        # 轮转均衡：任意两流计数差 ≤ 1
        counts = list(per_flow.values())
        assert max(counts) - min(counts) <= 1

        # 源端口互异且为 1024 + flow 序号（raw IP 包 UDP 头 offset 20）
        sports = {int.from_bytes(p[20:22], "big") for p in sent_packets}
        assert sports == {1024, 1025, 1026, 1027, 1028}

        # send_mode 枚举
        assert result["send_mode"] in {"raw", "udp", "scapy"}
        assert result["send_mode"] == "raw"

        # effective_pps = total / elapsed（round 2 位），数值合理
        total = result["packets_sent"]["total"]
        assert result["effective_pps"] == round(total / result["elapsed_s"], 2)
        assert 0 < result["effective_pps"] <= 30  # pps=20 附近，容差

        # 契约新增字段（T011/T012 已定型）
        assert result["completed"] is True
        assert result["clamped"] == []

    def test_flow_count_three_falls_back_to_scapy(self):
        """所有 socket 均不可用时回退 scapy：仍轮转且计数均衡。"""
        from src.tools.traffic_send_tool import traffic_send_tool

        with patch("src.tools.traffic_send_tool._create_raw_socket",
                   return_value=None), \
             patch("src.tools.traffic_send_tool._create_udp_sockets",
                   return_value=None), \
             patch("src.tools.traffic_send_tool.send"), \
             patch("src.tools.traffic_send_tool.HAS_SCAPY", True):
            result = traffic_send_tool(
                ALLOWLISTED_IP, dst_port=8080,
                duration_s=1, pps=20, flow_count=3,
            )

        assert result["send_mode"] == "scapy"
        counts = list(result["packets_sent"]["per_flow"].values())
        assert max(counts) - min(counts) <= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
