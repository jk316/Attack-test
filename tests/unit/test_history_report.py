"""Unit tests for the history report generator (normalization + session split)."""

import pytest

from scripts.generate_history_report import (
    _categorize,
    _infer_tool,
    build_session_summary,
    normalize_record,
    split_sessions,
)


def _rec(iteration, params, rtt=1.0, ts="2026-01-01T00:00:00"):
    return {"iteration": iteration, "params": params, "rtt": rtt, "loss": 0.0, "timestamp": ts}


# ── normalization ────────────────────────────────────────────────

class TestNormalize:
    def test_tool_field(self):
        r = normalize_record(_rec(1, {"tool": "pktgen_udp_flood", "dst_ip": "100.1.11.4", "rate": 5}))
        assert r["tool"] == "pktgen_udp_flood"
        assert r["category"] == "UDP 洪水"
        assert r["rate"] == 5.0

    def test_protocol_field(self):
        r = normalize_record(_rec(1, {"protocol": "pktgen_tcp_flood", "dst_ip": "100.1.11.4", "tcp_flags": "syn"}))
        assert r["tool"] == "pktgen_tcp_flood"
        assert r["category"] == "TCP SYN 洪水"

    def test_infer_mixed_from_streams(self):
        r = normalize_record(_rec(1, {"dst_ip": "100.1.11.4", "streams": "udp50+tcp30", "pps": 200}))
        assert r["tool"] == "mixed_traffic_send"

    def test_infer_traffic_send(self):
        r = normalize_record(_rec(1, {"dst_ip": "100.1.11.4", "dst_port": 80, "pps": 100}))
        assert r["tool"] == "traffic_send"

    def test_dport_alias(self):
        r = normalize_record(_rec(1, {"tool": "pktgen_udp_flood", "dst_ip": "100.1.11.4", "dport": 28763}))
        assert r["dst_port"] == 28763

    def test_duration_ms_to_s(self):
        r = normalize_record(_rec(1, {"tool": "pktgen_udp_flood", "dst_ip": "100.1.11.4", "duration_ms": 5000}))
        assert r["duration_s"] == 5.0

    def test_pktSize_alias(self):
        r = normalize_record(_rec(1, {"tool": "pktgen_udp_flood", "dst_ip": "100.1.11.4", "pktSize": 64}))
        assert r["packet_size"] == 64

    def test_categorize_unknown(self):
        assert _categorize("something_else") == "其他"
        assert _categorize("pktgen_range_scan") == "范围扫描"


class TestInferTool:
    def test_rate_without_tool(self):
        assert _infer_tool({"rate": 10, "dst_ip": "x"}) == "pktgen_udp_flood"

    def test_mixed_keys(self):
        assert _infer_tool({"traffic_type": "mixed"}) == "mixed_traffic_send"
        assert _infer_tool({"traffic_spec_json": "x"}) == "mixed_traffic_send"

    def test_default_traffic_send(self):
        assert _infer_tool({"dst_port": 80, "pps": 100}) == "traffic_send"


class TestCategorize:
    def test_trex_tcp_syn(self):
        assert _categorize("trex_stl_tcp_syn_flood") == "TRex TCP SYN"
        assert _categorize("trex_stl_tcp_syn_flood_mixed") == "TRex TCP SYN"

    def test_trex_udp(self):
        assert _categorize("trex_stl_udp_flood") == "TRex UDP"
        assert _categorize("trex_udp") == "TRex UDP"

    def test_trex_icmp(self):
        assert _categorize("trex_icmp") == "TRex ICMP"

    def test_descriptive_scapy(self):
        assert _categorize("UDP (Scapy)") == "Scapy UDP"
        assert _categorize("UDP (Scapy high load)") == "Scapy UDP"

    def test_descriptive_mixed(self):
        assert _categorize("Mixed (Scapy)") == "混合流量"

    def test_suffixed_tool(self):
        assert _categorize("traffic_send_max") == "Scapy UDP"
        assert _categorize("mixed_traffic_send_tcp_syn") == "混合流量"

    def test_descriptive_udp_flood(self):
        assert _categorize("UDP Flood (Pktgen)") == "UDP 洪水"

    def test_packet_sequence(self):
        assert _categorize("pktgen_packet_sequence") == "范围扫描"

    def test_still_unknown(self):
        assert _categorize("totally_bogus_tool") == "其他"


# ── session splitting ────────────────────────────────────────────

class TestSplitSessions:
    def test_split_on_iteration_reset(self):
        records = [
            _rec(1, {}, ts="2026-01-01T00:00:00"),
            _rec(2, {}, ts="2026-01-01T00:00:05"),
            _rec(1, {}, ts="2026-01-01T00:10:00"),
            _rec(2, {}, ts="2026-01-01T00:10:05"),
            _rec(3, {}, ts="2026-01-01T00:10:10"),
        ]
        sessions = split_sessions(records)
        assert len(sessions) == 2
        assert [r["session_id"] for r in records] == [0, 0, 1, 1, 1]
        assert [len(s["records"]) for s in sessions] == [2, 3]

    def test_summary_aggregation(self):
        raw = [
            _rec(1, {"tool": "traffic_send", "dst_ip": "100.1.11.4"}, rtt=1.0, ts="2026-01-01T00:00:00"),
            _rec(2, {"tool": "pktgen_tcp_flood", "dst_ip": "100.1.11.4"}, rtt=3.0, ts="2026-01-01T00:00:05"),
        ]
        records = [normalize_record(r) for r in raw]
        sessions = split_sessions(records)
        summary = build_session_summary(sessions)
        assert len(summary) == 1
        assert summary[0]["rounds"] == 2
        assert summary[0]["avg_rtt"] == 2.0
        assert summary[0]["max_rtt"] == 3.0
        assert summary[0]["max_rtt_attack"] == "TCP SYN 洪水"
        assert summary[0]["dst_ips"] == ["100.1.11.4"]
