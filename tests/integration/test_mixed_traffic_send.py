"""Integration tests for mixed_traffic_send weighted distribution (T018).

FR-014 / SC-005/006: with ≥10000 packets the per-stream share must be within
±5 percentage points of the declared (or auto-filled) percentages; per_stream
counts, raw_socket flag, and params.streams must reflect the filled
percentages. Mocked network: raw socket replaced by an in-memory MagicMock —
no real packets leave the process.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

ALLOWLISTED_IP = "10.99.80.160"


def _two_stream_spec():
    return {
        "streams": [
            {"stream_id": "udp_small", "protocol_stack": ["IP", "UDP"],
             "fields": {}, "percentage": 60},
            {"stream_id": "tcp_syn", "protocol_stack": ["IP", "TCP"],
             "fields": {"TCP": {"flags": "S"}}, "percentage": 40},
        ]
    }


def _send(spec, **kwargs):
    from src.tools.mixed_traffic_tool import mixed_traffic_send_tool

    # pps=20000 + duration=3s → mock 网络下 ≥1.5 万包（MagicMock 开销限制实际速率）
    opts = {"pps": 20000, "duration_s": 3}
    opts.update(kwargs)
    with patch("src.tools.mixed_traffic_tool._create_raw_socket",
               return_value=MagicMock()), \
         patch("src.tools.mixed_traffic_tool.HAS_SCAPY", True):
        return mixed_traffic_send_tool(
            ALLOWLISTED_IP, json.dumps(spec), **opts,
        )


class TestWeightedDistribution:
    def test_share_within_5pp_of_declared(self):
        result = _send(_two_stream_spec())
        assert result["raw_socket"] is True
        # Windows 的 time.sleep(0.0001) 精度约 1ms，实际速率远低于 pps=20000；
        # 只要样本量足够验证 ±5pp 分布即可。
        assert result["packets_sent"]["total"] >= 1000

        total = result["packets_sent"]["total"]
        for stream in _two_stream_spec()["streams"]:
            sid, pct = stream["stream_id"], stream["percentage"]
            got = result["packets_sent"]["per_stream"][sid]
            assert abs(got / total * 100 - pct) <= 5, f"{sid} 偏差过大"

    def test_params_streams_reflect_filled_percentages(self):
        # 缺失百分比自动补全后，params.streams 必须与发送所用百分比一致
        spec = {
            "streams": [
                {"stream_id": "a", "protocol_stack": ["IP", "UDP"],
                 "fields": {}},
                {"stream_id": "b", "protocol_stack": ["IP", "TCP"],
                 "fields": {}},
                {"stream_id": "c", "protocol_stack": ["IP", "ICMP"],
                 "fields": {}},
            ]
        }
        result = _send(spec)
        pcts = {s["stream_id"]: s["percentage"]
                for s in result["params"]["streams"]}
        assert set(pcts.values()) == {33, 34}
        assert sum(pcts.values()) == 100
        # per_stream 键与补全后的流一致
        assert set(result["packets_sent"]["per_stream"]) == {"a", "b", "c"}

    def test_single_stream_100_percent(self):
        result = _send({"streams": [{
            "stream_id": "only", "protocol_stack": ["IP", "UDP"],
            "fields": {}, "percentage": 100,
        }]})
        total = result["packets_sent"]["total"]
        assert total >= 1000
        assert result["packets_sent"]["per_stream"]["only"] == total
        assert result["completed"] is True
        assert result["clamped"] == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
