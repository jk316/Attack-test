"""Unit tests for the flattened experiment.json config (all params in one file).

No LLM, network, or real config file — CONFIG_PATH is pointed at a temp file.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

FLAT_CONFIG = {
    "target_ip": "10.99.80.160",
    "pcap_path": "",
    "log_path": "data/experiment.jsonl",
    "max_iters": 20,
    "no_improve_limit": 5,
    "auto_approve": True,
    "verbose": True,
    "pktgen_live": False,
    "trex_live": False,
    "trex_explore": False,
    "catalog_target": 12,
    "explore_direction": "",
    "instruction": "重点探索UDP洪水",
    "attack": {
        "duration_s": 10,
        "pps": 100,
        "packet_size": 64,
        "flow_count": 1,
        "iat_jitter_ms": 7,
    },
    "pktgen": {"rate": 50, "duration_ms": 10000, "host": None, "port": None},
    "trex": {"timeout_s": 30, "host": None, "port": None},
}


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(FLAT_CONFIG), encoding="utf-8")
    monkeypatch.setattr("src.main.CONFIG_PATH", path)
    return path


def _parse(argv: list[str]):
    with patch.object(sys, "argv", ["main.py", *argv]):
        from src.main import parse_args
        return parse_args()


class TestFlatConfigDefaults:
    def test_bare_run_reads_all_json_fields(self, config_file):
        """No CLI args → every param (incl. formerly CLI-only) comes from json."""
        args = _parse([])
        assert args.auto_approve is True
        assert args.verbose is True
        assert args.pktgen_live is False
        assert args.trex_live is False
        assert args.trex_explore is False
        assert args.catalog_target == 12
        assert args.instruction == "重点探索UDP洪水"
        assert args.iat_jitter == 7

    def test_no_profile_attribute(self, config_file):
        """--profile was removed along with the profiles mechanism."""
        args = _parse([])
        assert not hasattr(args, "profile")

    def test_host_port_null_falls_back(self, config_file):
        args = _parse([])
        assert args.pktgen_host is None
        assert args.pktgen_port is None
        assert args.trex_host is None
        assert args.trex_port is None

    def test_cli_still_overrides_json(self, config_file):
        args = _parse(["--instruction", "CLI覆盖", "--iat-jitter", "3"])
        assert args.instruction == "CLI覆盖"
        assert args.iat_jitter == 3
