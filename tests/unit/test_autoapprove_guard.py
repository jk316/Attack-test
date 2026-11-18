"""auto-approve × 实发模式互斥测试（008-T014）。

--auto-approve 与 --pktgen-live 或 --trex-live 组合 → 启动即报错退出
（exit≠0、中文原因）；单独 --auto-approve（dry-run）不报错；
--trex-explore×--trex-live 既有互斥保持。
"""

import sys
from unittest.mock import patch

import pytest


def _parse(argv):
    with patch.object(sys, "argv", ["main.py", *argv]):
        from src.main import parse_args
        return parse_args()


class TestAutoApproveLiveMutex:
    @pytest.mark.parametrize("live_flag", ["--pktgen-live", "--trex-live"])
    def test_auto_approve_with_live_rejected(self, live_flag):
        with pytest.raises(SystemExit) as excinfo:
            _parse(["--auto-approve", live_flag])
        assert excinfo.value.code != 0

    def test_auto_approve_alone_ok(self):
        args = _parse(["--auto-approve"])
        assert args.auto_approve is True
        assert args.pktgen_live is False
        assert args.trex_live is False

    def test_explore_trex_live_mutex_preserved(self):
        with pytest.raises(SystemExit) as excinfo:
            _parse(["--trex-explore", "--trex-live"])
        assert excinfo.value.code != 0

    def test_explore_with_auto_approve_is_ok(self):
        """explore 模式零流量零审批，--auto-approve 组合无害（不误伤）。"""
        args = _parse(["--trex-explore", "--auto-approve"])
        assert args.trex_explore is True
        assert args.auto_approve is True
