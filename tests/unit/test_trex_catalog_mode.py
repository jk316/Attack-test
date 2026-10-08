"""Unit tests for the TRex attack catalog exploration mode (--trex-explore).

Covers mode threading through build_graph (tool subset + prompt template),
CLI flags (mutual exclusion, defaults, env forcing), and the user message
builder. No LLM, network, or file I/O — all external calls are mocked.
"""
import argparse
import sys
from unittest.mock import patch

import pytest

from src.agent.graph import _build_system_prompt, build_graph
from src.agent.tools import EXPERIMENT_TOOLS
from src.trex.tools import TREX_TOOLS


def _parse(argv: list[str]) -> argparse.Namespace:
    """Parse CLI args with a fresh sys.argv."""
    with patch.object(sys, "argv", ["main.py", *argv]):
        from src.main import parse_args
        return parse_args()


# ── CLI: flags, defaults, mutual exclusion ──────────────────────────

class TestCatalogCliArgs:
    def test_explore_defaults(self):
        args = _parse(["--trex-explore"])
        assert args.trex_explore is True
        assert args.trex_live is False
        assert args.max_iters == 40  # explore default (prompt budget)
        assert args.catalog_target == 10

    def test_experiment_default_max_iters_unchanged(self):
        args = _parse([])
        assert args.trex_explore is False
        assert args.max_iters == 20  # experiment.json default

    def test_explore_with_trex_live_conflicts(self):
        with pytest.raises(SystemExit):
            _parse(["--trex-explore", "--trex-live"])

    def test_explore_max_iters_override(self):
        args = _parse(["--trex-explore", "--max-iters", "15", "--catalog-target", "5"])
        assert args.max_iters == 15
        assert args.catalog_target == 5

    def test_apply_mode_env_forces_dry_run(self, monkeypatch):
        import os

        from src.main import _apply_mode_env

        monkeypatch.delenv("TREX_DRY_RUN", raising=False)
        monkeypatch.delenv("CATALOG_TARGET", raising=False)
        _apply_mode_env(argparse.Namespace(trex_explore=True, catalog_target=7))
        assert os.environ.get("TREX_DRY_RUN") == "true"
        assert os.environ.get("CATALOG_TARGET") == "7"

    def test_apply_mode_env_noop_in_experiment_mode(self, monkeypatch):
        import os

        from src.main import _apply_mode_env

        monkeypatch.delenv("TREX_DRY_RUN", raising=False)
        monkeypatch.setenv("TREX_DRY_RUN", "false")
        _apply_mode_env(argparse.Namespace(trex_explore=False, catalog_target=7))
        assert os.environ.get("TREX_DRY_RUN") == "false"  # untouched

    def test_recursion_limit_covers_max_iters(self):
        from src.main import _recursion_limit

        assert _recursion_limit(40) == 45  # explore mode budget
        assert _recursion_limit(20) == 25  # create_agent default floor


# ── User message ────────────────────────────────────────────────────

class TestCatalogUserMessage:
    def test_explore_message(self):
        from src.main import _build_user_message

        msg = _build_user_message(
            argparse.Namespace(trex_explore=True, catalog_target=12, max_iters=40)
        )
        assert "TRex 攻击能力探索" in msg
        assert "≥12" in msg
        assert "dry-run" in msg
        assert "不发送任何流量" in msg

    def test_experiment_message(self):
        from src.main import _build_user_message

        msg = _build_user_message(
            argparse.Namespace(
                trex_explore=False, target_ip="10.99.80.160", pcap_path="",
                max_iters=20, no_improve_limit=5, log_path="data/x.jsonl",
            )
        )
        assert "闭环网络实验" in msg
        assert "10.99.80.160" in msg


# ── Prompt rendering ────────────────────────────────────────────────

class TestCatalogPrompt:
    def test_catalog_prompt_contains_core_constraints(self, monkeypatch):
        monkeypatch.setenv("CATALOG_TARGET", "7")
        prompt = _build_system_prompt(mode="catalog")
        assert "TRex 攻击能力探索" in prompt
        assert "cat_" in prompt                       # filename prefix rule
        assert "攻击名称" in prompt and "攻击类别" in prompt  # annotation block
        assert "脚本文件" in prompt                    # summary table column
        assert "dry-run" in prompt
        assert "7" in prompt                          # rendered catalog target

    def test_default_mode_uses_experiment_prompt(self):
        prompt = _build_system_prompt(mode="experiment")
        assert "闭环网络实验" in prompt
        assert "攻击能力探索" not in prompt


# ── build_graph mode threading ──────────────────────────────────────

class TestBuildGraphCatalogMode:
    def test_catalog_mode_restricts_tools_to_trex(self):
        captured = {}

        def fake_create_agent(**kwargs):
            captured.update(kwargs)
            return object()

        with patch("src.agent.graph._build_model", return_value=object()), \
             patch("src.agent.graph.create_agent", side_effect=fake_create_agent):
            build_graph(mode="catalog", max_iters=40)

        tools = captured["tools"]
        assert tools == TREX_TOOLS
        assert len(tools) == 2  # write_python_file + run_python_file only
        for traffic_tool in EXPERIMENT_TOOLS:
            if traffic_tool not in TREX_TOOLS:
                assert traffic_tool not in tools
        assert "攻击能力探索" in captured["system_prompt"]

    def test_default_mode_keeps_full_tool_set(self):
        captured = {}

        def fake_create_agent(**kwargs):
            captured.update(kwargs)
            return object()

        with patch("src.agent.graph._build_model", return_value=object()), \
             patch("src.agent.graph.create_agent", side_effect=fake_create_agent):
            build_graph()

        assert captured["tools"] == EXPERIMENT_TOOLS
        assert "闭环网络实验" in captured["system_prompt"]
