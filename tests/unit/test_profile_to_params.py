"""Unit tests for src/tools/profile_to_params.py (T014 / G-004 / SC-007).

确定性映射规则（contracts/pcap-profile.md §2）与回落/钳制；以及
src/main.py 的 CLI 接入（T016：CLI 显式参数 > 映射值 > 配置默认）。
纯函数，无 I/O。
"""
import argparse
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.tools.profile_to_params import profile_to_params


def _profile(**overrides):
    base = {
        "top_dst_ports": [53, 123],
        "packet_size_hist": {"64": 0.2, "128": 0.5, "256": 0.3},
        "iat_ms_stats": {"mean": 10.0, "p50": 10.0, "p90": 25.0},
        "flow_stats": {"approx_flow_count": 8, "timeout_s": 30},
    }
    base.update(overrides)
    return base


class TestMappingRules:
    def test_contract_example(self):
        """契约 §3 示例：dst_port=53、packet_size=128、flow_count=8、pps=100。"""
        result = profile_to_params(_profile(), defaults={"duration_s": 10})
        assert result == {"dst_port": 53, "packet_size": 128,
                          "flow_count": 8, "pps": 100, "duration_s": 10}

    def test_empty_port_ranking_falls_back(self):
        result = profile_to_params(_profile(top_dst_ports=[]),
                                   defaults={"dst_port": 8080})
        assert result["dst_port"] == 8080

    def test_packet_size_median_bucket_first_cumulative(self):
        # 64 桶概率 0.6 ≥ 0.5 → 取 64
        result = profile_to_params(
            _profile(packet_size_hist={"64": 0.6, "128": 0.4}))
        assert result["packet_size"] == 64

    def test_packet_size_other_bucket_maps_to_1024(self):
        result = profile_to_params(
            _profile(packet_size_hist={"64": 0.2, "128": 0.2, "other": 0.6}))
        assert result["packet_size"] == 1024

    def test_empty_histogram_falls_back(self):
        result = profile_to_params(_profile(packet_size_hist={}),
                                   defaults={"packet_size": 64})
        assert result["packet_size"] == 64

    def test_pps_from_iat_mean(self):
        result = profile_to_params(_profile(iat_ms_stats={"mean": 20.0}))
        assert result["pps"] == 50  # 1000/20

    def test_pps_falls_back_when_mean_zero(self):
        result = profile_to_params(_profile(iat_ms_stats={"mean": 0.0}),
                                   defaults={"pps": 100})
        assert result["pps"] == 100

    def test_pps_falls_back_when_no_iat(self):
        result = profile_to_params(_profile(iat_ms_stats={}),
                                   defaults={"pps": 100})
        assert result["pps"] == 100

    def test_duration_keeps_default(self):
        result = profile_to_params(_profile(), defaults={"duration_s": 10})
        assert result["duration_s"] == 10


class TestClamping:
    def test_flow_count_clamped(self):
        assert profile_to_params(
            _profile(flow_stats={"approx_flow_count": 500}))["flow_count"] == 100
        assert profile_to_params(
            _profile(flow_stats={"approx_flow_count": 0}))["flow_count"] == 1

    def test_pps_clamped(self):
        assert profile_to_params(
            _profile(iat_ms_stats={"mean": 0.0001}))["pps"] == 20000
        assert profile_to_params(
            _profile(iat_ms_stats={"mean": 100000.0}))["pps"] == 1

    def test_packet_size_clamped_to_1024(self):
        result = profile_to_params(
            _profile(packet_size_hist={"other": 1.0}))
        assert result["packet_size"] == 1024

    def test_dst_port_clamped(self):
        result = profile_to_params(_profile(top_dst_ports=[99999]))
        assert result["dst_port"] == 65535

    def test_duration_clamped_to_20(self):
        result = profile_to_params(_profile(), defaults={"duration_s": 99})
        assert result["duration_s"] == 20


class TestCliSeedIntegration:
    """T016：main.py 画像种子接入与人工覆盖（research 决策 1）。"""

    def _args(self, pcap_path, explicit=frozenset(), **params):
        base = dict(pps=100, packet_size=64, flow_count=1, duration=10)
        base.update(params)
        ns = argparse.Namespace(
            pcap_path=pcap_path, trex_explore=False,
            _explicit_flags=set(explicit), **base,
        )
        return ns

    def test_seeds_applied_when_pcap_and_not_explicit(self, monkeypatch):
        from src import main as main_mod

        import importlib
        mod = importlib.import_module("src.tools.pcap_profile_tool")
        monkeypatch.setattr(mod, "pcap_profile_tool", lambda **kw: _profile())
        monkeypatch.setattr("src.tools.profile_to_params.profile_to_params",
                            lambda profile, defaults: profile_to_params(
                                profile, defaults))

        args = self._args("data/sample.pcap")
        mapped = main_mod._apply_profile_seeds(args)
        assert mapped is not None
        assert args.pps == mapped["pps"]
        assert args.packet_size == mapped["packet_size"]
        assert args.flow_count == mapped["flow_count"]
        assert args.duration == mapped["duration_s"]
        assert args.profile_seeds == mapped

    def test_explicit_cli_overrides_seed(self, monkeypatch):
        from src import main as main_mod

        import importlib
        mod = importlib.import_module("src.tools.pcap_profile_tool")
        monkeypatch.setattr(mod, "pcap_profile_tool", lambda **kw: _profile())
        monkeypatch.setattr("src.tools.profile_to_params.profile_to_params",
                            lambda profile, defaults: profile_to_params(
                                profile, defaults))

        args = self._args("data/sample.pcap", explicit={"pps"}, pps=500)
        main_mod._apply_profile_seeds(args)
        assert args.pps == 500  # CLI 显式参数优先
        assert args.packet_size != 64  # 其余字段仍被映射注入

    def test_no_pcap_returns_none(self):
        from src import main as main_mod

        assert main_mod._apply_profile_seeds(
            self._args("")) is None

    def test_profile_failure_falls_back(self, monkeypatch, capsys):
        from src import main as main_mod

        def boom(**kw):
            raise ValueError("bad pcap")

        import importlib
        mod = importlib.import_module("src.tools.pcap_profile_tool")
        monkeypatch.setattr(mod, "pcap_profile_tool", boom)
        args = self._args("data/bad.pcap")
        assert main_mod._apply_profile_seeds(args) is None
        assert "画像失败" in capsys.readouterr().err

    def test_parse_args_tracks_explicit_flags(self):
        with patch.object(sys, "argv", [
            "main.py", "--pps", "500", "--max-iters", "3",
        ]):
            from src.main import parse_args
            args = parse_args()
        assert "pps" in args._explicit_flags
        assert "packet_size" not in args._explicit_flags


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
