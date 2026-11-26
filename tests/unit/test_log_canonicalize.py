"""Tests for the canonical log schema (canonicalize_params / canonicalize_entry)."""
import json

import pytest

from src.tools.log_tool import (
    canonicalize_entry,
    canonicalize_params,
    generate_run_id,
)


class TestCanonicalizeParams:
    def test_alias_normalization(self):
        canon = canonicalize_params({
            "dst_ip": "10.99.80.160",
            "dport": 80,
            "duration_ms": 5000,
            "pktSize": 64,
            "pps": 100,
            "proto": "udp",
        })
        assert canon["target_ip"] == "10.99.80.160"
        assert canon["dst_port"] == 80
        assert canon["duration_ms"] == 5000
        assert canon["pkt_size"] == 64
        assert canon["pps"] == 100
        assert canon["protocol"] == "udp"
        assert canon["extras"] is None  # nothing left over
        assert canon["results"] == {}

    def test_duration_s_converted_to_ms(self):
        canon = canonicalize_params({"dst_ip": "x", "duration_s": 5})
        assert canon["duration_ms"] == 5000

    def test_duration_ms_wins_over_duration_s(self):
        canon = canonicalize_params({"duration_ms": 3000, "duration_s": 5})
        assert canon["duration_ms"] == 3000

    def test_unitless_duration_is_not_guessed(self):
        canon = canonicalize_params({"duration": 5000})
        assert canon["duration_ms"] is None
        assert canon["extras"]["duration"] == 5000

    def test_rate_maps_to_rate_pct_only_for_pktgen(self):
        pkt = canonicalize_params({"rate": 50}, tool="pktgen_udp_flood")
        assert pkt["rate_pct"] == 50
        assert "rate" not in (pkt["extras"] or {})

        scapy = canonicalize_params({"rate": 50}, tool="traffic_send")
        assert scapy["rate_pct"] is None
        assert scapy["extras"]["rate"] == 50

    def test_result_keys_are_stripped_into_results(self):
        canon = canonicalize_params({
            "dst_ip": "x", "pps": 100, "tx_gbps": 1.2, "note": "hi",
        })
        assert canon["results"] == {"note": "hi", "tx_gbps": 1.2}
        assert "tx_gbps" not in (canon["extras"] or {})

    def test_unknown_keys_preserved_in_extras(self):
        canon = canonicalize_params({
            "dst_ip": "x", "tcp_flags": "S", "scan_field": "port",
        })
        assert canon["extras"] == {"scan_field": "port", "tcp_flags": "S"}

    def test_flags_alias_merged_into_tcp_flags(self):
        canon = canonicalize_params({"dst_ip": "x", "flags": "S"})
        assert canon["extras"]["tcp_flags"] == "S"
        assert "flags" not in canon["extras"]

    def test_non_dict_params_wrapped_raw(self):
        canon = canonicalize_params("oops")
        assert canon["extras"] == {"_raw_params": "oops"}
        assert canon["results"] == {}


class TestCanonicalizeEntry:
    def test_full_entry_layout(self, monkeypatch):
        monkeypatch.delenv("DSH_RUN_ID", raising=False)
        entry = {
            "iteration": 3,
            "params": {
                "dst_ip": "10.99.80.160", "dport": 80, "duration_s": 5,
                "packet_size": 64, "pps": 100, "proto": "tcp",
                "tcp_flags": "S", "tx_gbps": 1.1,
            },
            "rtt": 0.98,
            "loss": 0.0,
            "timestamp": "2026-11-20T07:00:00+00:00",
        }
        rec = canonicalize_entry(entry)
        assert list(rec.keys()) == [
            "run_id", "iteration", "tool", "params", "results", "rtt", "loss",
            "timestamp",
        ]
        assert rec["run_id"] == "unknown"
        assert rec["tool"] == "unknown"
        assert rec["params"]["target_ip"] == "10.99.80.160"
        assert rec["params"]["dst_port"] == 80
        assert rec["params"]["duration_ms"] == 5000
        assert rec["params"]["pkt_size"] == 64
        assert rec["params"]["protocol"] == "tcp"
        assert rec["params"]["extras"] == {"tcp_flags": "S"}
        assert rec["results"] == {"tx_gbps": 1.1}
        # caller-provided timestamp is preserved verbatim
        assert rec["timestamp"] == "2026-11-20T07:00:00+00:00"

    def test_tool_taken_from_params_when_entry_has_none(self):
        rec = canonicalize_entry({
            "iteration": 1,
            "params": {"tool": "pktgen_udp_flood", "rate": 50, "dst_ip": "x"},
            "rtt": 1.0, "loss": 0.0,
        })
        assert rec["tool"] == "pktgen_udp_flood"
        assert rec["params"]["rate_pct"] == 50

    def test_explicit_results_merged_with_stripped(self):
        rec = canonicalize_entry({
            "iteration": 1,
            "params": {"dst_ip": "x", "note": "stripped"},
            "results": {"extra": 1, "note": "explicit"},
            "rtt": 1.0, "loss": 0.0,
        })
        assert rec["results"] == {"note": "explicit", "extra": 1}

    def test_run_id_prefers_entry_then_env(self, monkeypatch):
        monkeypatch.setenv("DSH_RUN_ID", "env-run")
        assert canonicalize_entry({"params": {}, "rtt": 1, "loss": 0})["run_id"] == "env-run"
        assert canonicalize_entry(
            {"run_id": "entry-run", "params": {}, "rtt": 1, "loss": 0}
        )["run_id"] == "entry-run"

    def test_generate_run_id_format(self):
        rid = generate_run_id()
        assert len(rid) == 22  # YYYYmmddTHHMMSS-hex6
        assert rid[8] == "T"
        assert rid[15] == "-"

    def test_roundtrip_through_log_tool(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DSH_RUN_ID", "test-run")
        from src.tools.log_tool import log_tool

        log_path = tmp_path / "t.jsonl"
        result = log_tool(str(log_path), {
            "iteration": 7,
            "tool": "traffic_send",
            "params": {"dst_ip": "10.99.80.160", "dst_port": 80, "pps": 50},
            "rtt": 2.0,
            "loss": 1.0,
        })
        assert result["success"] is True
        line = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert line["run_id"] == "test-run"
        assert line["tool"] == "traffic_send"
        assert line["params"]["target_ip"] == "10.99.80.160"
        assert line["params"]["dst_port"] == 80
        assert line["params"]["pps"] == 50
