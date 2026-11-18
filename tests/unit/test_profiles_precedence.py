"""profiles 优先级测试（008-T013）。

对照 contracts/experiment-config.md 语义规则 1/3：显式 CLI > profile >
基础配置；未知 profile 报错并列出全部可用预设名。
"""

import sys
from unittest.mock import patch

import pytest


def _parse(argv):
    with patch.object(sys, "argv", ["main.py", *argv]):
        from src.main import parse_args
        return parse_args()


class TestProfilesPrecedence:
    def test_base_config_defaults(self):
        args = _parse([])
        assert args.pps == 100          # experiment.json attack.pps
        assert args.duration == 10
        assert args.max_iters == 20

    def test_profile_overrides_base(self):
        args = _parse(["--profile", "high_pps"])
        assert args.pps == 2000         # profile high_pps
        assert args.duration == 5
        # 未覆盖字段回落基础配置
        assert args.packet_size == 64

    def test_cli_overrides_profile(self):
        args = _parse(["--profile", "high_pps", "--pps", "5000"])
        assert args.pps == 5000         # 显式 CLI 最高优先

    def test_pktgen_profile_section(self):
        args = _parse(["--profile", "pktgen_max"])
        assert args.pktgen_rate == 100
        assert args.pktgen_duration == 30000

    def test_unknown_profile_errors_with_names(self):
        """未知 profile → SystemExit（非 0 语义），消息列出全部可用预设名。"""
        with pytest.raises(SystemExit) as excinfo:
            _parse(["--profile", "nope_profile"])
        msg = str(excinfo.value)
        assert "未知 profile" in msg
        assert "high_pps" in msg
        assert "long_run" in msg
        assert "pktgen_max" in msg
