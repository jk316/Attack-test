"""TRex 配置 getter 与输出截断的契约补测（006-T006，US1）。

锁定 contracts/trex-run-gates.md 第 4 节口径：超时钳制 (0,300]、
host/port env 优先与拓扑回退、dry-run 仅显式 "false" 为 live、
_ 输出截断 4000 字符附 `…(+N chars)`。
"""

import os

import pytest

from src.trex import config as trex_config
from src.trex.tools import _truncate


class TestGetTrexTimeoutS:
    """get_trex_timeout_s() 钳制语义。"""

    @pytest.mark.parametrize("env_value,expected", [
        ("45", 45.0),        # (0,300] 内取配置值
        ("300", 300.0),      # 上界含
        ("0", 30.0),         # 0 → 默认
        ("-5", 30.0),        # 负数 → 默认
        ("301", 30.0),       # 超 300 → 默认
        ("abc", 30.0),       # 非法值 → 默认
        ("", 30.0),          # 空串 → 默认
    ])
    def test_timeout_clamp(self, monkeypatch, env_value, expected):
        monkeypatch.setenv("TREX_TIMEOUT_S", env_value)
        assert trex_config.get_trex_timeout_s() == expected

    def test_timeout_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("TREX_TIMEOUT_S", raising=False)
        assert trex_config.get_trex_timeout_s() == 30.0


class TestTrexHostPort:
    """host/port env 优先与拓扑回退。"""

    def test_host_env_priority(self, monkeypatch):
        monkeypatch.setenv("TREX_HOST", "192.0.2.99")
        assert trex_config.get_trex_host() == "192.0.2.99"

    def test_host_topology_fallback(self, monkeypatch):
        monkeypatch.delenv("TREX_HOST", raising=False)
        host = trex_config.get_trex_host()
        assert host  # topology.yaml trex.host（10.99.80.222）或内置默认
        assert host in ("10.99.80.222", trex_config._DEFAULT_HOST)

    def test_host_builtin_default_when_no_topology(self, monkeypatch):
        monkeypatch.delenv("TREX_HOST", raising=False)
        monkeypatch.setattr(trex_config, "_load_trex_section", lambda: {})
        assert trex_config.get_trex_host() == "127.0.0.1"

    def test_port_env_priority(self, monkeypatch):
        monkeypatch.setenv("TREX_PORT", "5555")
        assert trex_config.get_trex_port() == 5555

    def test_port_env_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("TREX_PORT", "not-a-port")
        port = trex_config.get_trex_port()
        assert port in (4501, trex_config._DEFAULT_PORT)

    def test_port_topology_fallback(self, monkeypatch):
        monkeypatch.delenv("TREX_PORT", raising=False)
        assert trex_config.get_trex_port() == 4501

    def test_port_builtin_default_when_no_topology(self, monkeypatch):
        monkeypatch.delenv("TREX_PORT", raising=False)
        monkeypatch.setattr(trex_config, "_load_trex_section", lambda: {})
        assert trex_config.get_trex_port() == 4501


class TestIsTrexDryRun:
    """is_trex_dry_run()：仅显式 "false"（大小写不敏感）为 live。"""

    @pytest.mark.parametrize("env_value,expected", [
        ("true", True),
        ("True", True),
        ("1", True),          # 任何非 "false" 值都保持 dry-run
        ("yes", True),
        ("", True),
        ("false", False),     # 显式 false → live
        ("FALSE", False),
    ])
    def test_dry_run_semantics(self, monkeypatch, env_value, expected):
        monkeypatch.setenv("TREX_DRY_RUN", env_value)
        assert trex_config.is_trex_dry_run() is expected

    def test_dry_run_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("TREX_DRY_RUN", raising=False)
        assert trex_config.is_trex_dry_run() is True


class TestTruncate:
    """_truncate() 截断 4000 字符并附 `…(+N chars)` 后缀。"""

    def test_short_output_unchanged(self):
        text = "short output"
        assert _truncate(text) == text

    def test_exactly_limit_unchanged(self):
        text = "x" * 4000
        assert _truncate(text) == text

    def test_long_output_truncated_with_annotation(self):
        text = "y" * 5000
        out = _truncate(text)
        assert out == "y" * 4000 + "… (+1000 chars)"
        assert len(out) == 4000 + len("… (+1000 chars)")

    def test_none_becomes_empty(self):
        assert _truncate(None) == ""
