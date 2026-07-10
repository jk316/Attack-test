"""Integration tests: config file → env vars → tool defaults pipeline.

Verifies that experiment.json settings flow correctly through the tool
layer without requiring Pktgen or any network access.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ALLOWLISTED_IP = "10.99.80.160"


@pytest.fixture
def set_env_from_config():
    """Simulate what main.py does: read config, set env vars."""
    config = {
        "attack": {
            "duration_s": 12,
            "pps": 333,
            "packet_size": 128,
            "flow_count": 4,
            "iat_jitter_ms": 2,
        },
        "pktgen": {
            "rate": 77,
            "duration_ms": 9999,
        },
    }
    for k, v in config["attack"].items():
        os.environ[f"ATK_{k.upper()}"] = str(v)
    os.environ["PKTGEN_RATE"] = str(config["pktgen"]["rate"])
    os.environ["PKTGEN_DURATION_MS"] = str(config["pktgen"]["duration_ms"])
    yield
    for k in config["attack"]:
        os.environ.pop(f"ATK_{k.upper()}", None)
    os.environ.pop("PKTGEN_RATE", None)
    os.environ.pop("PKTGEN_DURATION_MS", None)


class TestConfigToToolDefaults:
    """Verify config values flow through env vars to tool defaults."""

    def test_traffic_send_uses_env_defaults(self, set_env_from_config):
        """traffic_send should pick up defaults from env vars."""
        from src.agent.tools import traffic_send

        with patch("src.agent.tools.traffic_send_tool") as mock_send, \
             patch("src.agent.tools.interrupt", return_value=True):
            mock_send.return_value = {"success": True}

            # Call without specifying duration_s/pps/etc — should use env
            traffic_send.invoke({
                "dst_ip": ALLOWLISTED_IP, "dst_port": 8080,
            })

            _, kwargs = mock_send.call_args
            assert kwargs["duration_s"] == 12
            assert kwargs["pps"] == 333
            assert kwargs["packet_size"] == 128
            assert kwargs["flow_count"] == 4
            assert kwargs["iat_jitter_ms"] == 2

    def test_traffic_send_explicit_overrides_env(self, set_env_from_config):
        """Explicit arguments should override env var defaults."""
        from src.agent.tools import traffic_send

        with patch("src.agent.tools.traffic_send_tool") as mock_send, \
             patch("src.agent.tools.interrupt", return_value=True):
            mock_send.return_value = {"success": True}

            traffic_send.invoke({
                "dst_ip": ALLOWLISTED_IP, "dst_port": 8080,
                "duration_s": 3, "pps": 50,
            })

            _, kwargs = mock_send.call_args
            assert kwargs["duration_s"] == 3   # explicit
            assert kwargs["pps"] == 50          # explicit
            assert kwargs["packet_size"] == 128  # from env

    def test_mixed_traffic_send_uses_env_defaults(self, set_env_from_config):
        """mixed_traffic_send should pick up defaults from env vars."""
        from src.agent.tools import mixed_traffic_send

        with patch("src.agent.tools.mixed_traffic_send_tool") as mock_send, \
             patch("src.agent.tools.interrupt", return_value=True):
            mock_send.return_value = {"success": True}

            mixed_traffic_send.invoke({
                "dst_ip": ALLOWLISTED_IP,
                "traffic_spec_json": '[{"stream_id":"s1","protocol_stack":["IP","UDP"],"fields":{},"percentage":100}]',
            })

            _, kwargs = mock_send.call_args
            assert kwargs["duration_s"] == 12
            assert kwargs["pps"] == 333

    def test_pktgen_defaults_flow_to_adapter(self, set_env_from_config):
        """Pktgen env vars should set adapter function defaults."""
        from src.pktgen.adapter import get_pktgen_host, get_pktgen_port, is_dry_run

        # Rate and duration are read from env at call time by the adapter tools.
        # Verify the env vars are set correctly.
        assert os.environ.get("PKTGEN_RATE") == "77"
        assert os.environ.get("PKTGEN_DURATION_MS") == "9999"
        # Host/port still read from topology.yaml (not affected by this config)
        host = get_pktgen_host()
        assert host  # should be whatever topology.yaml says
        # Dry-run default is True
        assert is_dry_run() is True

    def test_config_rendered_in_system_prompt(self, set_env_from_config):
        """System prompt should include the env var values."""
        from jinja2 import Environment, FileSystemLoader

        env = Environment(loader=FileSystemLoader("src/prompts"))
        template = env.get_template("system_prompt.j2")
        rendered = template.render(
            max_pps=20000, max_duration_s=20, max_packet_size=1024,
            max_flow_count=100, max_iat_jitter_ms=20,
            max_iters=20, no_improve_limit=5,
            atk_duration_s=int(os.environ.get("ATK_DURATION_S", "5")),
            atk_pps=int(os.environ.get("ATK_PPS", "100")),
            atk_packet_size=int(os.environ.get("ATK_PACKET_SIZE", "64")),
            atk_flow_count=int(os.environ.get("ATK_FLOW_COUNT", "1")),
            pktgen_rate=os.environ.get("PKTGEN_RATE", "50"),
            pktgen_duration_ms=os.environ.get("PKTGEN_DURATION_MS", "5000"),
            pktgen_available=True, pktgen_dry_run=True,
            pktgen_host="10.99.80.222", pktgen_port="22022",
        )
        assert "默认 12" in rendered  # duration_s
        assert "默认 333" in rendered  # pps
        assert "默认 128" in rendered  # packet_size
        assert "默认 4" in rendered  # flow_count
        assert "rate=77%" in rendered
        assert "duration=9999ms" in rendered

    def test_experiment_json_has_required_keys(self):
        """Verify experiment.json contains the expected config sections."""
        config_path = Path("src/config/experiment.json")
        with open(config_path) as f:
            data = json.load(f)

        attack = data.get("attack", {})
        assert "duration_s" in attack
        assert "pps" in attack
        assert "packet_size" in attack
        assert "flow_count" in attack
        assert "iat_jitter_ms" in attack

        pktgen = data.get("pktgen", {})
        assert "rate" in pktgen
        assert "duration_ms" in pktgen
