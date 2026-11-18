"""门控矩阵一致性测试（008-T009）。

断言 src/pktgen/adapter.py 的 _SKILLS_WITH_DST_IP 与 _SKILLS_WITH_HITL
与 data-model「门控矩阵」契约一致（arp_flood/pcap_replay 免 allowlist 但
保留 HITL；stats_monitoring/safe_stop_and_reset 均不在 HITL 集合）。
"""

from src.pktgen.adapter import _SKILLS_WITH_DST_IP, _SKILLS_WITH_HITL


class TestGateMatrix:
    def test_skills_with_dst_ip(self):
        assert _SKILLS_WITH_DST_IP == {
            "udp_flood", "tcp_flood", "icmp_flood",
            "range_based_scan", "packet_sequence_generation",
        }

    def test_skills_with_hitl(self):
        assert _SKILLS_WITH_HITL == {
            "udp_flood", "tcp_flood", "icmp_flood", "arp_flood",
            "range_based_scan", "packet_sequence_generation", "pcap_replay",
        }

    def test_arp_flood_free_of_allowlist_but_keeps_hitl(self):
        assert "arp_flood" not in _SKILLS_WITH_DST_IP
        assert "arp_flood" in _SKILLS_WITH_HITL

    def test_pcap_replay_free_of_allowlist_but_keeps_hitl(self):
        assert "pcap_replay" not in _SKILLS_WITH_DST_IP
        assert "pcap_replay" in _SKILLS_WITH_HITL

    def test_ops_skills_hitl_free(self):
        assert "stats_monitoring" not in _SKILLS_WITH_HITL
        assert "safe_stop_and_reset" not in _SKILLS_WITH_HITL
        assert "stats_monitoring" not in _SKILLS_WITH_DST_IP
        assert "safe_stop_and_reset" not in _SKILLS_WITH_DST_IP


class TestHitlPayloadShapeG3:
    """008-G3：_hitl_gate 审批 payload 为 {message, params, scope}。"""

    def test_hitl_gate_payload_unified(self):
        from unittest.mock import patch

        from src.pktgen.adapter import _hitl_gate

        captured = {}

        def fake_interrupt(payload):
            captured.update(payload)
            return True

        with patch("src.pktgen.adapter.is_dry_run", return_value=False), \
             patch("src.pktgen.adapter.interrupt", side_effect=fake_interrupt):
            result = _hitl_gate("udp_flood", {"dst_ip": ALLOWED, "rate": 50})

        assert result is True
        assert "message" in captured
        assert captured["scope"] == "pktgen_traffic"
        params = captured["params"]
        assert params["skill"] == "udp_flood"
        assert params["mode"] == "live"
        assert params["rate"] == 50


ALLOWED = "10.99.80.160"
