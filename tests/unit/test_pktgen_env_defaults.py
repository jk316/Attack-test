"""Pktgen 工具默认值 env 注入链测试（008-T012，005-G4 实现归属）。

设置 PKTGEN_RATE/PKTGEN_DURATION_MS 后调用 @tool（不给显式参数），
断言默认值取 env 值；缺省回落签名默认（50 / 5000）；显式参数优先。
⚠️ 全部 mock 执行器（R11），零流量零硬件。
"""

from unittest.mock import MagicMock, patch

import pytest

ALLOWED_IP = "10.99.80.160"

FLOODS = ["pktgen_udp_flood", "pktgen_tcp_flood", "pktgen_icmp_flood", "pktgen_arp_flood"]


def _invoke_capture(tool_name, params, monkeypatch=None):
    from src.pktgen import adapter

    tool = getattr(adapter, tool_name)
    with patch.object(adapter, "_execute_skill") as mock_exec:
        mock_exec.return_value = {"success": True, "mode": "dry_run"}
        tool.invoke(params)
        return mock_exec.call_args[0][1]


class TestRateDurationEnvDefaults:
    @pytest.mark.parametrize("tool_name", FLOODS)
    def test_env_values_used_when_omitted(self, tool_name, monkeypatch):
        monkeypatch.setenv("PKTGEN_RATE", "80")
        monkeypatch.setenv("PKTGEN_DURATION_MS", "3000")
        params = {"rate": 50}  # rate 显式，duration 省略
        if tool_name != "pktgen_arp_flood":
            params["dst_ip"] = ALLOWED_IP
        engine_params = _invoke_capture(tool_name, params)
        assert engine_params["rate"] == 50          # 显式优先
        assert engine_params["duration"] == 3000    # env 生效

    @pytest.mark.parametrize("tool_name", FLOODS)
    def test_rate_from_env_when_omitted(self, tool_name, monkeypatch):
        monkeypatch.setenv("PKTGEN_RATE", "80")
        monkeypatch.delenv("PKTGEN_DURATION_MS", raising=False)
        params = {}
        if tool_name != "pktgen_arp_flood":
            params["dst_ip"] = ALLOWED_IP
        engine_params = _invoke_capture(tool_name, params)
        assert engine_params["rate"] == 80.0
        assert engine_params["duration"] == 5000  # 回退签名默认

    @pytest.mark.parametrize("tool_name", FLOODS)
    def test_fallback_to_signature_defaults(self, tool_name, monkeypatch):
        monkeypatch.delenv("PKTGEN_RATE", raising=False)
        monkeypatch.delenv("PKTGEN_DURATION_MS", raising=False)
        params = {}
        if tool_name != "pktgen_arp_flood":
            params["dst_ip"] = ALLOWED_IP
        engine_params = _invoke_capture(tool_name, params)
        assert engine_params["rate"] == 50.0
        assert engine_params["duration"] == 5000

    @pytest.mark.parametrize("tool_name", FLOODS)
    def test_explicit_params_override_env(self, tool_name, monkeypatch):
        monkeypatch.setenv("PKTGEN_RATE", "80")
        monkeypatch.setenv("PKTGEN_DURATION_MS", "3000")
        params = {"rate": 10, "duration": 2000}
        if tool_name != "pktgen_arp_flood":
            params["dst_ip"] = ALLOWED_IP
        engine_params = _invoke_capture(tool_name, params)
        assert engine_params["rate"] == 10
        assert engine_params["duration"] == 2000

    def test_invalid_env_value_falls_back(self, monkeypatch):
        monkeypatch.setenv("PKTGEN_RATE", "not-a-number")
        monkeypatch.setenv("PKTGEN_DURATION_MS", "xyz")
        engine_params = _invoke_capture(
            "pktgen_udp_flood", {"dst_ip": ALLOWED_IP},
        )
        assert engine_params["rate"] == 50.0
        assert engine_params["duration"] == 5000

    def test_range_scan_rate_from_env(self, monkeypatch):
        monkeypatch.setenv("PKTGEN_RATE", "66")
        engine_params = _invoke_capture("pktgen_range_scan", {
            "dst_ip": ALLOWED_IP, "scan_field": "dst_port",
            "start": "1", "min_val": "1", "max_val": "100", "inc": "1",
        })
        assert engine_params["rate"] == 66.0

    def test_sequence_replay_keep_full_line_rate_default(self, monkeypatch):
        """packet_sequence/pcap_replay 的 rate=100 语义默认不受 env 覆盖
        （满线速是工具语义，非 experiment.json 可调默认值）。"""
        monkeypatch.setenv("PKTGEN_RATE", "50")
        import json as _json
        seq = _json.dumps([{
            "eth_dst_addr": "00:11:44:55:66:77",
            "eth_src_addr": "00:11:12:34:56:78",
            "ip_dst_addr": ALLOWED_IP, "ip_src_addr": "10.0.0.1",
            "sport": 9, "dport": 10, "ethType": "ipv4", "ipProto": "udp",
            "vlanid": 1, "pktSize": 128,
        }])
        from src.pktgen import adapter

        with patch.object(adapter, "_execute_skill") as mock_exec:
            mock_exec.return_value = {"success": True}
            adapter.pktgen_packet_sequence.invoke({
                "dst_ip": ALLOWED_IP, "sequences": seq,
            })
            seq_params = mock_exec.call_args[0][1]
            assert seq_params["rate"] == 100.0

            adapter.pktgen_pcap_replay.invoke({"pcap_file": "/tmp/x.pcap"})
            replay_params = mock_exec.call_args[0][1]
            assert replay_params["rate"] == 100.0
