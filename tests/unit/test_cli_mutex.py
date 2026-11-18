"""Unit tests for CLI mutual exclusion and catalog-mode env injection (T020).

Covers (G6 / FR-012 / contracts §3): --trex-explore × --trex-live aborts at
startup before any side effect; catalog mode defaults max_iters=40; and the
CATALOG_TARGET / EXPLORE_DIRECTION env injection through
src/main.py::parse_args + _apply_mode_env. No LLM, network, or file I/O.
"""
import os
import sys
from unittest.mock import patch

import pytest

from src.main import parse_args, _apply_mode_env


def _parse(argv: list[str]):
    with patch.object(sys, "argv", ["main.py", *argv]):
        return parse_args()


class TestMutualExclusion:
    def test_explore_with_live_exits_nonzero(self):
        with pytest.raises(SystemExit) as exc:
            _parse(["--trex-explore", "--trex-live"])
        assert exc.value.code != 0

    def test_error_message_is_chinese_and_names_both_flags(self, capsys):
        with pytest.raises(SystemExit):
            _parse(["--trex-explore", "--trex-live"])
        err = capsys.readouterr().err
        assert "--trex-explore" in err
        assert "--trex-live" in err
        assert "互斥" in err  # contracts §4：stderr 输出中文原因

    def test_error_occurs_before_any_env_side_effect(self, monkeypatch):
        monkeypatch.delenv("TREX_DRY_RUN", raising=False)
        with pytest.raises(SystemExit):
            _parse(["--trex-explore", "--trex-live"])
        # 互斥报错发生在模式 env 注入之前——无副作用
        assert "TREX_DRY_RUN" not in os.environ


class TestCatalogDefaults:
    def test_catalog_default_max_iters_40(self):
        args = _parse(["--trex-explore"])
        assert args.max_iters == 40

    def test_catalog_default_catalog_target_10(self):
        args = _parse(["--trex-explore"])
        assert args.catalog_target == 10

    def test_cli_overrides_catalog_defaults(self):
        args = _parse(["--trex-explore", "--max-iters", "60",
                       "--catalog-target", "15"])
        assert args.max_iters == 60
        assert args.catalog_target == 15


class TestCatalogEnvInjection:
    """CATALOG_TARGET / EXPLORE_DIRECTION / TREX_DRY_RUN 经 _apply_mode_env 注入。"""

    def test_catalog_target_injected(self, monkeypatch):
        monkeypatch.delenv("CATALOG_TARGET", raising=False)
        monkeypatch.delenv("TREX_DRY_RUN", raising=False)
        args = _parse(["--trex-explore", "--catalog-target", "23"])
        _apply_mode_env(args)
        assert os.environ["TREX_DRY_RUN"] == "true"
        assert os.environ["CATALOG_TARGET"] == "23"

    def test_explore_direction_injected_when_nonempty(self, monkeypatch):
        monkeypatch.delenv("EXPLORE_DIRECTION", raising=False)
        args = _parse(["--trex-explore",
                       "--explore-direction", "重点探索DNS放大攻击"])
        _apply_mode_env(args)
        assert os.environ["EXPLORE_DIRECTION"] == "重点探索DNS放大攻击"

    def test_explore_direction_not_set_when_empty(self, monkeypatch):
        monkeypatch.delenv("EXPLORE_DIRECTION", raising=False)
        args = _parse(["--trex-explore"])
        _apply_mode_env(args)
        assert "EXPLORE_DIRECTION" not in os.environ

    def test_no_injection_in_experiment_mode(self, monkeypatch):
        monkeypatch.delenv("CATALOG_TARGET", raising=False)
        monkeypatch.delenv("TREX_DRY_RUN", raising=False)
        monkeypatch.delenv("EXPLORE_DIRECTION", raising=False)
        args = _parse(["--catalog-target", "30",
                       "--explore-direction", "x"])
        _apply_mode_env(args)
        assert "CATALOG_TARGET" not in os.environ
        assert "TREX_DRY_RUN" not in os.environ
        assert "EXPLORE_DIRECTION" not in os.environ


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
