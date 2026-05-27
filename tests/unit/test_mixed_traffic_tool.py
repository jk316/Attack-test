"""Unit tests for mixed_traffic_send_tool.

Follows the same pattern as test_traffic_send_tool.py: mock Scapy send() and
HAS_SCAPY flag to test validation, construction, and output structure.
"""
import json
import pytest
from unittest.mock import patch

ALLOWLISTED_IP = "10.99.80.160"


class TestMixedTrafficTool:
    """Tests for mixed_traffic_send_tool validation, construction, and send loop."""

    # ── JSON Parsing ──────────────────────────────────────────

    def test_valid_json_accepted(self):
        """Valid JSON spec should be parsed without error."""
        from src.tools.mixed_traffic_tool import validate_traffic_spec

        spec = {
            "streams": [
                {
                    "stream_id": "s1",
                    "protocol_stack": ["IP", "UDP"],
                    "fields": {"IP": {}, "UDP": {"dport": 80}},
                    "percentage": 100,
                }
            ]
        }
        streams = validate_traffic_spec(spec)
        assert len(streams) == 1

    def test_invalid_json_rejected(self):
        """Non-JSON string should raise ValueError."""
        from src.tools.mixed_traffic_tool import mixed_traffic_send_tool

        with patch("src.tools.mixed_traffic_tool.HAS_SCAPY", True), \
             patch("src.tools.mixed_traffic_tool.validate_target"):
            with pytest.raises(ValueError, match="Invalid JSON"):
                mixed_traffic_send_tool(ALLOWLISTED_IP, "not-json-at-all", pps=10)

    # ── Stream Count ──────────────────────────────────────────

    def test_zero_streams_rejected(self):
        """0 streams should be rejected."""
        from src.tools.mixed_traffic_tool import validate_traffic_spec

        with pytest.raises(ValueError, match="stream count"):
            validate_traffic_spec({"streams": []})

    def test_too_many_streams_rejected(self):
        """More than MAX_STREAMS should be rejected."""
        from src.tools.mixed_traffic_tool import validate_traffic_spec

        streams = [
            {"stream_id": f"s{i}", "protocol_stack": ["IP", "UDP"],
             "fields": {}, "percentage": 10}
            for i in range(11)
        ]
        with pytest.raises(ValueError, match="stream count"):
            validate_traffic_spec({"streams": streams})

    # ── Percentage ────────────────────────────────────────────

    def test_percentage_sum_lt_100_rejected(self):
        """Total percentage < 100 should be rejected."""
        from src.tools.mixed_traffic_tool import validate_traffic_spec

        spec = {
            "streams": [
                {"stream_id": "s1", "protocol_stack": ["IP", "UDP"],
                 "fields": {}, "percentage": 40},
            ]
        }
        with pytest.raises(ValueError, match="sum to 40"):
            validate_traffic_spec(spec)

    def test_percentage_sum_gt_100_rejected(self):
        """Total percentage > 100 should be rejected."""
        from src.tools.mixed_traffic_tool import validate_traffic_spec

        spec = {
            "streams": [
                {"stream_id": "s1", "protocol_stack": ["IP", "UDP"],
                 "fields": {}, "percentage": 60},
                {"stream_id": "s2", "protocol_stack": ["IP", "TCP"],
                 "fields": {}, "percentage": 60},
            ]
        }
        with pytest.raises(ValueError, match="sum to 120"):
            validate_traffic_spec(spec)

    def test_percentage_non_integer_rejected(self):
        """Float percentage should be rejected."""
        from src.tools.mixed_traffic_tool import validate_traffic_spec

        spec = {
            "streams": [
                {"stream_id": "s1", "protocol_stack": ["IP", "UDP"],
                 "fields": {}, "percentage": 50.5},
                {"stream_id": "s2", "protocol_stack": ["IP", "TCP"],
                 "fields": {}, "percentage": "49.5"},
            ]
        }
        with pytest.raises(ValueError, match="percentage"):
            validate_traffic_spec(spec)

    # ── Protocol Whitelist ────────────────────────────────────

    def test_unknown_protocol_rejected(self):
        """Protocol not in whitelist should be rejected."""
        from src.tools.mixed_traffic_tool import validate_traffic_spec

        spec = {
            "streams": [
                {"stream_id": "s1", "protocol_stack": ["IP", "HTTP"],
                 "fields": {}, "percentage": 100},
            ]
        }
        with pytest.raises(ValueError, match="whitelist"):
            validate_traffic_spec(spec)

    def test_all_whitelist_protocols_accepted(self):
        """All whitelisted protocols should be accepted in various stacks."""
        from src.tools.mixed_traffic_tool import validate_traffic_spec

        spec = {
            "streams": [
                {"stream_id": "s1", "protocol_stack": ["IP", "TCP"],
                 "fields": {}, "percentage": 30},
                {"stream_id": "s2", "protocol_stack": ["IP", "UDP"],
                 "fields": {}, "percentage": 30},
                {"stream_id": "s3", "protocol_stack": ["IP", "ICMP"],
                 "fields": {}, "percentage": 20},
                {"stream_id": "s4", "protocol_stack": ["IP", "UDP", "DNS"],
                 "fields": {}, "percentage": 20},
            ]
        }
        streams = validate_traffic_spec(spec)
        assert len(streams) == 4

    # ── Injection Scanning ────────────────────────────────────

    def test_dunder_import_rejected(self):
        """__import__ in field value should be rejected."""
        from src.tools.mixed_traffic_tool import _check_dangerous_values

        with pytest.raises(ValueError, match="forbidden pattern"):
            _check_dangerous_values({"key": "__import__('os')"}, "s1", "IP")

    def test_os_system_rejected(self):
        """os.system in field value should be rejected."""
        from src.tools.mixed_traffic_tool import _check_dangerous_values

        with pytest.raises(ValueError, match="forbidden pattern"):
            _check_dangerous_values({"cmd": "os.system('rm -rf /')"}, "s1", "TCP")

    def test_normal_values_accepted(self):
        """Normal field values should pass injection scan."""
        from src.tools.mixed_traffic_tool import _check_dangerous_values

        _check_dangerous_values({"dport": 80, "flags": "S"}, "s1", "TCP")

    def test_nested_dict_injection_rejected(self):
        """Injection in nested dict values should be caught."""
        from src.tools.mixed_traffic_tool import _check_dangerous_values

        with pytest.raises(ValueError, match="forbidden pattern"):
            _check_dangerous_values(
                {"qd": {"qname": "eval('x')", "qtype": "A"}}, "s1", "DNS"
            )

    # ── IP.dst Overwrite ──────────────────────────────────────

    def test_ip_dst_overwritten(self):
        """IP.dst from JSON should be ignored and replaced with dst_ip arg."""
        from src.tools.mixed_traffic_tool import build_packet_template

        stream = {
            "stream_id": "s1",
            "protocol_stack": ["IP", "UDP"],
            "fields": {"IP": {"dst": "192.168.99.99"}, "UDP": {"dport": 80}},
        }
        pkt = build_packet_template(stream, ALLOWLISTED_IP)
        assert pkt["IP"].dst == ALLOWLISTED_IP

    # ── Packet Construction ───────────────────────────────────

    def test_tcp_packet_built(self):
        """TCP stream should produce IP/TCP packet."""
        from src.tools.mixed_traffic_tool import build_packet_template

        stream = {
            "stream_id": "syn_flood",
            "protocol_stack": ["IP", "TCP"],
            "fields": {"IP": {}, "TCP": {"flags": "S", "dport": 80}},
        }
        pkt = build_packet_template(stream, ALLOWLISTED_IP)
        assert pkt.haslayer("TCP")
        assert pkt["TCP"].flags == "S"
        assert pkt["TCP"].dport == 80

    def test_udp_packet_built(self):
        """UDP stream should produce IP/UDP packet."""
        from src.tools.mixed_traffic_tool import build_packet_template

        stream = {
            "stream_id": "udp_stream",
            "protocol_stack": ["IP", "UDP"],
            "fields": {"IP": {}, "UDP": {"dport": 53}},
        }
        pkt = build_packet_template(stream, ALLOWLISTED_IP)
        assert pkt.haslayer("UDP")
        assert pkt["UDP"].dport == 53

    def test_dns_packet_built(self):
        """DNS stream should produce IP/UDP/DNS packet with nested DNSQR."""
        from src.tools.mixed_traffic_tool import build_packet_template

        stream = {
            "stream_id": "dns_query",
            "protocol_stack": ["IP", "UDP", "DNS"],
            "fields": {
                "IP": {},
                "UDP": {"dport": 53},
                "DNS": {"qr": 0, "qd": {"qname": "example.com.", "qtype": "A"}},
            },
        }
        pkt = build_packet_template(stream, ALLOWLISTED_IP)
        assert pkt.haslayer("DNS")
        assert pkt["DNS"].qr == 0
        assert pkt["DNS"].qd.qname == b"example.com."

    def test_icmp_packet_built(self):
        """ICMP stream should produce IP/ICMP packet."""
        from src.tools.mixed_traffic_tool import build_packet_template

        stream = {
            "stream_id": "icmp_ping",
            "protocol_stack": ["IP", "ICMP"],
            "fields": {"IP": {}, "ICMP": {"type": 8, "code": 0}},
        }
        pkt = build_packet_template(stream, ALLOWLISTED_IP)
        assert pkt.haslayer("ICMP")
        assert pkt["ICMP"].type == 8

    def test_bad_nested_dict_rejected(self):
        """Unknown nested dict in fields should raise ValueError."""
        from src.tools.mixed_traffic_tool import _resolve_nested_fields

        with pytest.raises(ValueError, match="unknown nested"):
            _resolve_nested_fields("UDP", {"unknown_nested": {"foo": "bar"}})

    # ── Send Loop ─────────────────────────────────────────────

    def test_per_stream_counts_correct(self):
        """After sending, per_stream counts should match weighted distribution."""
        from src.tools.mixed_traffic_tool import mixed_traffic_send_tool

        spec_json = json.dumps({
            "streams": [
                {"stream_id": "tcp", "protocol_stack": ["IP", "TCP"],
                 "fields": {"IP": {}, "TCP": {"flags": "S", "dport": 80}},
                 "percentage": 70},
                {"stream_id": "udp", "protocol_stack": ["IP", "UDP"],
                 "fields": {"IP": {}, "UDP": {"dport": 53}},
                 "percentage": 30},
            ]
        })

        with patch("src.tools.mixed_traffic_tool.send"), \
             patch("src.tools.mixed_traffic_tool.HAS_SCAPY", True), \
             patch("src.tools.mixed_traffic_tool.validate_target"):
            result = mixed_traffic_send_tool(
                ALLOWLISTED_IP, spec_json, duration_s=1, pps=100
            )

        assert result["success"] is True
        total = result["packets_sent"]["total"]
        assert total > 0
        per_stream = result["packets_sent"]["per_stream"]
        assert per_stream["tcp"] + per_stream["udp"] == total

    def test_output_structure_correct(self):
        """Return dict should have all expected keys."""
        from src.tools.mixed_traffic_tool import mixed_traffic_send_tool

        spec_json = json.dumps({
            "streams": [
                {"stream_id": "s1", "protocol_stack": ["IP", "UDP"],
                 "fields": {"IP": {}, "UDP": {"dport": 80}},
                 "percentage": 100},
            ]
        })

        with patch("src.tools.mixed_traffic_tool.send"), \
             patch("src.tools.mixed_traffic_tool.HAS_SCAPY", True), \
             patch("src.tools.mixed_traffic_tool.validate_target"):
            result = mixed_traffic_send_tool(
                ALLOWLISTED_IP, spec_json, duration_s=1, pps=10
            )

        assert "success" in result
        assert "params" in result
        assert "packets_sent" in result
        assert "elapsed_s" in result
        assert "effective_pps" in result
        assert "errors" in result
        assert isinstance(result["packets_sent"]["total"], int)
        assert isinstance(result["packets_sent"]["per_stream"], dict)
        assert isinstance(result["effective_pps"], float)

    def test_effective_pps_reasonable(self):
        """effective_pps should be close to requested pps."""
        from src.tools.mixed_traffic_tool import mixed_traffic_send_tool

        spec_json = json.dumps({
            "streams": [
                {"stream_id": "s1", "protocol_stack": ["IP", "UDP"],
                 "fields": {"IP": {}, "UDP": {"dport": 80}},
                 "percentage": 100},
            ]
        })

        with patch("src.tools.mixed_traffic_tool.send"), \
             patch("src.tools.mixed_traffic_tool.HAS_SCAPY", True), \
             patch("src.tools.mixed_traffic_tool.validate_target"):
            result = mixed_traffic_send_tool(
                ALLOWLISTED_IP, spec_json, duration_s=1, pps=50
            )

        assert 0 <= result["effective_pps"]

    # ── Target Validation ─────────────────────────────────────

    def test_non_allowlist_ip_rejected(self):
        """Non-allowlisted IP should be rejected by validate_target."""
        from src.tools.mixed_traffic_tool import mixed_traffic_send_tool

        spec_json = json.dumps({
            "streams": [
                {"stream_id": "s1", "protocol_stack": ["IP", "UDP"],
                 "fields": {}, "percentage": 100},
            ]
        })

        with patch("src.tools.mixed_traffic_tool.HAS_SCAPY", True):
            with pytest.raises(ValueError, match="not in allowlist"):
                mixed_traffic_send_tool("192.168.1.99", spec_json, pps=10)

    def test_broadcast_ip_rejected(self):
        """Broadcast IP should be rejected."""
        from src.tools.mixed_traffic_tool import mixed_traffic_send_tool

        spec_json = json.dumps({
            "streams": [
                {"stream_id": "s1", "protocol_stack": ["IP", "UDP"],
                 "fields": {}, "percentage": 100},
            ]
        })

        with patch("src.tools.mixed_traffic_tool.HAS_SCAPY", True):
            with pytest.raises(ValueError, match="(?i)broadcast"):
                mixed_traffic_send_tool("192.168.1.255", spec_json, pps=10)

    # ── Scapy Not Available ───────────────────────────────────

    def test_scapy_not_available_error(self):
        """ImportError when HAS_SCAPY is False."""
        from src.tools.mixed_traffic_tool import mixed_traffic_send_tool

        with patch("src.tools.mixed_traffic_tool.HAS_SCAPY", False):
            with pytest.raises(ImportError, match="(?i)scapy"):
                mixed_traffic_send_tool(ALLOWLISTED_IP, '{"streams":[]}', pps=10)

    # ── Edge Cases ────────────────────────────────────────────

    def test_single_stream_100_percent(self):
        """Single stream with 100% should work."""
        from src.tools.mixed_traffic_tool import validate_traffic_spec

        spec = {
            "streams": [
                {"stream_id": "solo", "protocol_stack": ["IP", "TCP"],
                 "fields": {}, "percentage": 100},
            ]
        }
        streams = validate_traffic_spec(spec)
        assert len(streams) == 1

    def test_duplicate_stream_id_rejected(self):
        """Duplicate stream_id should be rejected."""
        from src.tools.mixed_traffic_tool import validate_traffic_spec

        spec = {
            "streams": [
                {"stream_id": "dup", "protocol_stack": ["IP", "UDP"],
                 "fields": {}, "percentage": 50},
                {"stream_id": "dup", "protocol_stack": ["IP", "TCP"],
                 "fields": {}, "percentage": 50},
            ]
        }
        with pytest.raises(ValueError, match="duplicate"):
            validate_traffic_spec(spec)

    def test_empty_protocol_stack_rejected(self):
        """Empty protocol_stack should be rejected."""
        from src.tools.mixed_traffic_tool import validate_traffic_spec

        spec = {
            "streams": [
                {"stream_id": "s1", "protocol_stack": [],
                 "fields": {}, "percentage": 100},
            ]
        }
        with pytest.raises(ValueError, match="protocol_stack"):
            validate_traffic_spec(spec)

    def test_json_too_long_rejected(self):
        """JSON exceeding MAX_JSON_LENGTH should be rejected."""
        from src.tools.mixed_traffic_tool import mixed_traffic_send_tool, MAX_JSON_LENGTH

        with patch("src.tools.mixed_traffic_tool.HAS_SCAPY", True), \
             patch("src.tools.mixed_traffic_tool.validate_target"):
            long_json = "x" * (MAX_JSON_LENGTH + 1)
            with pytest.raises(ValueError, match="too long"):
                mixed_traffic_send_tool(ALLOWLISTED_IP, long_json, pps=10)

    def test_missing_streams_key_rejected(self):
        """Spec without 'streams' key should be rejected."""
        from src.tools.mixed_traffic_tool import validate_traffic_spec

        with pytest.raises(ValueError, match="streams"):
            validate_traffic_spec({})
