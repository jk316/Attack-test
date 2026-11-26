"""Unit tests for the TRex attack catalog exploration mode (--trex-explore).

Covers mode threading through build_graph (tool subset + prompt template),
CLI flags (mutual exclusion, defaults, env forcing), and the user message
builder. No LLM, network, or file I/O — all external calls are mocked.
"""
import argparse
import json
import sys
from unittest.mock import patch

import pytest

import src.main as main_mod
from src.agent.graph import _build_system_prompt, build_graph
from src.agent.tools import EXPERIMENT_TOOLS
from src.trex.tools import TREX_TOOLS

# Minimal runtime config so CLI defaults don't depend on the repo's
# experiment.json (which the experiment server edits at will).
MINIMAL_CFG = {
    "target_ip": "10.99.80.160",
    "pcap_path": "",
    "log_path": "data/experiment.jsonl",
    "max_iters": 20,
    "no_improve_limit": 5,
    "auto_approve": False,
    "verbose": False,
    "pktgen_live": False,
    "trex_live": False,
    "trex_explore": False,
    "catalog_target": 10,
    "explore_direction": "",
    "instruction": "",
    "attack": {"duration_s": 10, "pps": 100, "packet_size": 64, "flow_count": 1, "iat_jitter_ms": 0},
    "pktgen": {"rate": 50, "duration_ms": 10000},
    "trex": {},
    "http": {},
}


@pytest.fixture(autouse=True)
def _hermetic_config(tmp_path, monkeypatch):
    cfg_file = tmp_path / "experiment.json"
    cfg_file.write_text(json.dumps(MINIMAL_CFG), encoding="utf-8")
    monkeypatch.setattr(main_mod, "CONFIG_PATH", cfg_file)


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
        with pytest.raises(SystemExit) as excinfo:
            _parse(["--trex-explore", "--trex-live"])
        assert excinfo.value.code != 0  # 解析期报错，进程以非 0 退出码终止（FR-020）

    def test_explore_max_iters_override(self):
        args = _parse(["--trex-explore", "--max-iters", "15", "--catalog-target", "5"])
        assert args.max_iters == 15
        assert args.catalog_target == 5

    def test_explore_direction_default_empty(self):
        args = _parse(["--trex-explore"])
        assert args.explore_direction == ""

    def test_explore_direction_parsed(self):
        args = _parse(["--trex-explore", "--explore-direction",
                       "重点探索DNS放大攻击和TCP SYN洪水"])
        assert args.explore_direction == "重点探索DNS放大攻击和TCP SYN洪水"

    def test_apply_mode_env_forces_dry_run(self, monkeypatch):
        import os

        from src.main import _apply_mode_env

        monkeypatch.delenv("TREX_DRY_RUN", raising=False)
        monkeypatch.delenv("CATALOG_TARGET", raising=False)
        _apply_mode_env(argparse.Namespace(trex_explore=True, catalog_target=7,
                                           explore_direction=""))
        assert os.environ.get("TREX_DRY_RUN") == "true"
        assert os.environ.get("CATALOG_TARGET") == "7"

    def test_apply_mode_env_overrides_existing_live_env(self, monkeypatch):
        """探索模式即使 env 残留 "false" 也强制回 dry-run（FR-020 边界固化）。"""
        import os

        from src.main import _apply_mode_env

        monkeypatch.setenv("TREX_DRY_RUN", "false")  # 模拟先前 live 运行残留
        _apply_mode_env(argparse.Namespace(trex_explore=True, catalog_target=7,
                                           explore_direction=""))
        assert os.environ.get("TREX_DRY_RUN") == "true"

    def test_apply_mode_env_noop_in_experiment_mode(self, monkeypatch):
        import os

        from src.main import _apply_mode_env

        monkeypatch.delenv("TREX_DRY_RUN", raising=False)
        monkeypatch.delenv("EXPLORE_DIRECTION", raising=False)
        monkeypatch.setenv("TREX_DRY_RUN", "false")
        _apply_mode_env(argparse.Namespace(trex_explore=False, catalog_target=7,
                                           explore_direction="DNS放大"))
        assert os.environ.get("TREX_DRY_RUN") == "false"  # untouched
        assert "EXPLORE_DIRECTION" not in os.environ

    def test_apply_mode_env_sets_explore_direction(self, monkeypatch):
        import os

        from src.main import _apply_mode_env

        monkeypatch.delenv("EXPLORE_DIRECTION", raising=False)
        _apply_mode_env(argparse.Namespace(trex_explore=True, catalog_target=7,
                                           explore_direction="DNS放大"))
        assert os.environ.get("EXPLORE_DIRECTION") == "DNS放大"

    def test_recursion_limit_covers_max_iters(self):
        from src.main import _recursion_limit

        assert _recursion_limit(40) == 45  # explore mode budget
        assert _recursion_limit(20) == 25  # create_agent default floor


# ── User message ────────────────────────────────────────────────────

class TestCatalogUserMessage:
    def test_explore_message(self):
        from src.main import _build_user_message

        msg = _build_user_message(
            argparse.Namespace(trex_explore=True, catalog_target=12, max_iters=40,
                               explore_direction="")
        )
        assert "TRex 攻击能力探索" in msg
        assert "≥12" in msg
        assert "dry-run" in msg
        assert "不发送任何流量" in msg
        assert "探索方向" not in msg  # empty direction adds no line

    def test_explore_message_includes_direction(self):
        from src.main import _build_user_message

        msg = _build_user_message(
            argparse.Namespace(trex_explore=True, catalog_target=12, max_iters=40,
                               explore_direction="重点探索DNS放大")
        )
        assert "探索方向" in msg
        assert "重点探索DNS放大" in msg

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

    def test_explore_direction_rendered_when_set(self, monkeypatch):
        monkeypatch.setenv("EXPLORE_DIRECTION", "重点探索DNS放大攻击和TCP SYN洪水")
        prompt = _build_system_prompt(mode="catalog")
        assert "## 本次探索方向" in prompt
        assert "重点探索DNS放大攻击和TCP SYN洪水" in prompt

    def test_no_direction_section_when_unset(self, monkeypatch):
        monkeypatch.delenv("EXPLORE_DIRECTION", raising=False)
        empty = _build_system_prompt(mode="catalog")
        assert "本次探索方向" not in empty
        assert "重点覆盖以下方向" not in empty
        monkeypatch.setenv("EXPLORE_DIRECTION", "")
        assert _build_system_prompt(mode="catalog") == empty  # empty renders identically

    def test_catalog_prompt_contains_l2_mac_facts(self, monkeypatch):
        monkeypatch.setenv("TREX_DST_MAC", "aa:bb:cc:dd:ee:ff")
        monkeypatch.setenv("TREX_SRC_MAC", "11:22:33:44:55:66")
        prompt = _build_system_prompt(mode="catalog")
        assert "aa:bb:cc:dd:ee:ff" in prompt
        assert "11:22:33:44:55:66" in prompt
        assert "trex_common" in prompt
        assert "prepare_port" in prompt
        assert "make_astf_client" in prompt
        assert "网关" in prompt

    def test_catalog_prompt_hides_gateway_ip_literal(self, monkeypatch):
        prompt = _build_system_prompt(mode="catalog")
        assert "100.1.13.1" not in prompt

    def test_experiment_prompt_points_to_trex_skill(self, monkeypatch):
        """TRex 知识改为按需加载：实验 prompt 只留 load_skill 指针，不再内联 L2 事实。"""
        monkeypatch.setattr("src.agent.graph._trex_available", lambda: True)
        monkeypatch.setenv("TREX_DST_MAC", "aa:bb:cc:dd:ee:ff")
        prompt = _build_system_prompt(mode="experiment")
        assert "load_skill" in prompt
        assert "trex-astf" in prompt
        # L2 细节已移入 skill，不应再出现在实验 prompt 里
        assert "aa:bb:cc:dd:ee:ff" not in prompt
        assert "trex_common" not in prompt
        assert "start_safe" not in prompt

    def test_experiment_prompt_hides_gateway_ip_literal(self, monkeypatch):
        monkeypatch.setattr("src.agent.graph._trex_available", lambda: True)
        prompt = _build_system_prompt(mode="experiment")
        assert "100.1.13.1" not in prompt


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


# ── TRex L2 env plumbing ───────────────────────────────────────────

class TestTrexL2Env:
    def test_apply_trex_l2_env_sets_all(self, monkeypatch):
        import os

        from src.main import _apply_trex_l2_env

        for k in ("TREX_DST_MAC", "TREX_SRC_MAC", "TREX_START_FORCE"):
            monkeypatch.delenv(k, raising=False)
        _apply_trex_l2_env({"dst_mac": "aa:bb:cc:dd:ee:ff",
                            "src_mac": "11:22:33:44:55:66",
                            "start_force": False})
        assert os.environ["TREX_DST_MAC"] == "aa:bb:cc:dd:ee:ff"
        assert os.environ["TREX_SRC_MAC"] == "11:22:33:44:55:66"
        assert os.environ["TREX_START_FORCE"] == "False"

    def test_apply_trex_l2_env_missing_keys_noop(self, monkeypatch):
        import os

        from src.main import _apply_trex_l2_env

        for k in ("TREX_DST_MAC", "TREX_SRC_MAC", "TREX_START_FORCE"):
            monkeypatch.delenv(k, raising=False)
        _apply_trex_l2_env({})
        assert "TREX_DST_MAC" not in os.environ
        assert "TREX_SRC_MAC" not in os.environ
        assert "TREX_START_FORCE" not in os.environ
