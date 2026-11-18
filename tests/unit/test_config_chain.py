"""Unit tests for the config injection chain (T016 / G7 / FR-007/008/015 / SC-005/008).

Priority chain: CLI > named profile (deep merge of attack/pktgen/trex) >
experiment.json > built-in defaults. Unknown profiles abort with an error
that lists the available profiles. CONFIG_PATH is pointed at temp files; no
LLM, network, or real config mutation.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BASE_CONFIG = {
    "target_ip": "100.1.11.20",
    "pcap_path": "",
    "log_path": "data/experiment.jsonl",
    "max_iters": 20,
    "no_improve_limit": 5,
    "attack": {
        "duration_s": 10,
        "pps": 700,
        "packet_size": 64,
        "flow_count": 1,
        "iat_jitter_ms": 0,
    },
    "pktgen": {"rate": 50, "duration_ms": 10000},
    "trex": {"timeout_s": 30},
    "profiles": {
        "high_pps": {"attack": {"pps": 2000, "duration_s": 5}},
        "pktgen_max": {"pktgen": {"rate": 100, "duration_ms": 30000}},
    },
}


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(BASE_CONFIG), encoding="utf-8")
    monkeypatch.setattr("src.main.CONFIG_PATH", path)
    return path


@pytest.fixture
def no_config(monkeypatch, tmp_path):
    monkeypatch.setattr("src.main.CONFIG_PATH", tmp_path / "missing.json")
    return tmp_path / "missing.json"


def _parse(argv: list[str]):
    with patch.object(sys, "argv", ["main.py", *argv]):
        from src.main import parse_args
        return parse_args()


def _load(profile=None):
    from src.main import _load_config_defaults
    return _load_config_defaults(profile=profile)


class TestBuiltinDefaults:
    """无配置文件时回退内置默认（FR-007：默认 20 与 5）。"""

    def test_builtin_defaults_without_config(self, no_config):
        args = _parse([])
        assert args.target_ip == "10.99.80.160"
        assert args.max_iters == 20
        assert args.no_improve_limit == 5
        assert args.pps == 100
        assert args.packet_size == 64
        assert args.flow_count == 1
        assert args.pktgen_rate == 50
        assert args.pktgen_duration == 10000
        assert args.trex_timeout == 30

    def test_load_config_defaults_without_config(self, no_config):
        cfg = _load()
        assert cfg["max_iters"] == 20
        assert cfg["no_improve_limit"] == 5
        # attack 段不内置在 _load_config_defaults（内置攻击默认由 parse_args
        # 兜底提供，见 test_builtin_defaults_without_config）
        assert cfg.get("attack", {}).get("pps", 100) == 100


class TestConfigOverBuiltin:
    """experiment.json 覆盖内置默认。"""

    def test_config_values_override_builtin(self, config_file):
        args = _parse([])
        assert args.target_ip == "100.1.11.20"
        assert args.pps == 700  # 配置值覆盖内置 100
        assert args.duration == 10

    def test_config_scalars_flow(self, config_file):
        cfg = _load()
        assert cfg["target_ip"] == "100.1.11.20"
        assert cfg["max_iters"] == 20
        assert cfg["attack"]["duration_s"] == 10


class TestProfileOverConfig:
    """profile 深合并覆盖 attack/pktgen/trex 三组（只写变更键）。"""

    def test_profile_deep_merges_attack(self, config_file):
        args = _parse(["--profile", "high_pps"])
        assert args.pps == 2000            # profile 覆盖 config 700
        assert args.duration == 5          # profile 覆盖 config 10
        assert args.packet_size == 64      # config 键保留
        assert args.flow_count == 1

    def test_profile_deep_merges_pktgen_only(self, config_file):
        args = _parse(["--profile", "pktgen_max"])
        assert args.pktgen_rate == 100
        assert args.pktgen_duration == 30000
        assert args.pps == 700             # attack 组不受影响
        assert args.duration == 10
        assert args.trex_timeout == 30     # trex 组不受影响


class TestCliOverProfile:
    """CLI 显式参数 > profile > config（SC-005）。"""

    def test_cli_beats_profile(self, config_file):
        args = _parse(["--profile", "high_pps", "--pps", "999"])
        assert args.pps == 999
        assert args.duration == 5  # 其余仍来自 profile

    def test_cli_beats_config_without_profile(self, config_file):
        args = _parse(["--pps", "1234", "--duration", "7"])
        assert args.pps == 1234
        assert args.duration == 7

    def test_cli_budget_overrides_config(self, config_file):
        args = _parse(["--max-iters", "6", "--no-improve-limit", "2"])
        assert args.max_iters == 6
        assert args.no_improve_limit == 2


class TestUnknownProfile:
    def test_unknown_profile_exits(self, config_file):
        with pytest.raises(SystemExit):
            _parse(["--profile", "nope"])

    def test_unknown_profile_lists_available(self, config_file):
        with pytest.raises(SystemExit) as exc:
            _parse(["--profile", "nope"])
        msg = str(exc.value)
        assert "未知 profile" in msg
        assert "high_pps" in msg
        assert "pktgen_max" in msg


class TestTrexExploreBudget:
    def test_explore_mode_defaults_max_iters_40(self, config_file):
        args = _parse(["--trex-explore"])
        assert args.max_iters == 40  # catalog 默认 40（contracts §2）

    def test_explore_mode_cli_budget_wins(self, config_file):
        args = _parse(["--trex-explore", "--max-iters", "60"])
        assert args.max_iters == 60


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestJitterConfigInjection:
    """R4（Lead 裁定，归属 002）：ATK_IAT_JITTER_MS 经配置链注入。

    parse_args 从 attack.iat_jitter_ms（profile 感知、无新 CLI 参数）暴露
    args.iat_jitter_ms；_inject_attack_env 注入 env 供工具调用时读取。
    """

    def test_parse_exposes_jitter_from_config(self, config_file):
        args = _parse([])
        assert args.iat_jitter_ms == 0  # BASE_CONFIG attack.iat_jitter_ms=0

    def test_jitter_profile_overlay(self, config_file):
        # 在临时配置上追加带 jitter 的 profile，验证 profile 链生效
        from src.main import CONFIG_PATH

        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        data["profiles"]["jitter_hard"] = {"attack": {"iat_jitter_ms": 12}}
        CONFIG_PATH.write_text(json.dumps(data), encoding="utf-8")

        args = _parse(["--profile", "jitter_hard"])
        assert args.iat_jitter_ms == 12

    def test_inject_attack_env_sets_jitter(self, config_file, monkeypatch):
        import os

        from src.main import _inject_attack_env

        monkeypatch.delenv("ATK_IAT_JITTER_MS", raising=False)
        args = _parse([])
        _inject_attack_env(args)
        assert os.environ["ATK_IAT_JITTER_MS"] == "0"
        assert os.environ["ATK_PPS"] == "700"  # 其余注入键不受影响
