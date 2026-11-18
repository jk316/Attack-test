"""Unit tests for --profile named-preset loading (experiment.json profiles).

No LLM, network, or real config file — CONFIG_PATH is pointed at a temp file.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

BASE_CONFIG = {
    "target_ip": "10.99.80.160",
    "pcap_path": "",
    "log_path": "data/experiment.jsonl",
    "max_iters": 20,
    "no_improve_limit": 5,
    "attack": {
        "duration_s": 10,
        "pps": 100,
        "packet_size": 64,
        "flow_count": 1,
        "iat_jitter_ms": 0,
    },
    "pktgen": {"rate": 50, "duration_ms": 10000},
    "trex": {"timeout_s": 30},
    "profiles": {
        "high_pps": {"attack": {"pps": 2000, "duration_s": 5}},
        "long_run": {"max_iters": 40, "attack": {"duration_s": 20, "pps": 500}},
        "pktgen_max": {"pktgen": {"rate": 100, "duration_ms": 30000}},
    },
}


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(BASE_CONFIG), encoding="utf-8")
    monkeypatch.setattr("src.main.CONFIG_PATH", path)
    return path


def _parse(argv: list[str]):
    with patch.object(sys, "argv", ["main.py", *argv]):
        from src.main import parse_args
        return parse_args()


def _load(profile=None):
    from src.main import _load_config_defaults
    return _load_config_defaults(profile=profile)


# ── _load_config_defaults ──────────────────────────────────────────

class TestLoadConfigDefaults:
    def test_no_profile_uses_base_defaults(self, config_file):
        cfg = _load()
        assert cfg["target_ip"] == "10.99.80.160"
        assert cfg["attack"]["pps"] == 100
        assert cfg["pktgen"]["rate"] == 50

    def test_profile_overrides_nested_section(self, config_file):
        cfg = _load(profile="high_pps")
        assert cfg["attack"]["pps"] == 2000
        assert cfg["attack"]["duration_s"] == 5
        # untouched keys from base survive the merge
        assert cfg["attack"]["packet_size"] == 64
        assert cfg["max_iters"] == 20

    def test_profile_overrides_scalar(self, config_file):
        cfg = _load(profile="long_run")
        assert cfg["max_iters"] == 40
        assert cfg["attack"]["duration_s"] == 20

    def test_unknown_profile_raises(self, config_file):
        with pytest.raises(SystemExit):
            _load(profile="nope")

    def test_profile_does_not_mutate_base(self, config_file):
        base = _load()
        _load(profile="high_pps")
        assert base["attack"]["pps"] == 100
        assert base["max_iters"] == 20


# ── parse_args integration ─────────────────────────────────────────

class TestParseArgsProfile:
    def test_profile_sets_arg_defaults(self, config_file):
        args = _parse(["--profile", "high_pps"])
        assert args.profile == "high_pps"
        assert args.pps == 2000
        assert args.duration == 5
        assert args.max_iters == 20  # untouched by high_pps

    def test_profile_scalar_flows_to_max_iters(self, config_file):
        args = _parse(["--profile", "long_run"])
        assert args.max_iters == 40

    def test_explicit_cli_overrides_profile(self, config_file):
        args = _parse(["--profile", "high_pps", "--pps", "999"])
        assert args.pps == 999        # explicit wins
        assert args.duration == 5     # from profile

    def test_unknown_profile_exits(self, config_file):
        with pytest.raises(SystemExit):
            _parse(["--profile", "nope"])
