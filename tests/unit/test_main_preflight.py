"""Unit tests for the startup preflight (G3 / FR-017 / data-model 校验规则).

Target must be in the allowlist, max_iters ≥ 1, no_improve_limit ≥ 1; the
--trex-explore × --trex-live combination must abort at startup. Violations
exit non-zero with a Chinese error message on stderr; compliant parameters
continue. No LLM, network, or traffic — preflight runs before graph build.
"""
import sys
from unittest.mock import patch

import pytest

from src.main import parse_args, _run_preflight

ALLOWED = "10.99.80.160"
REJECTED = "192.168.1.99"


def _parse(argv: list[str]):
    with patch.object(sys, "argv", ["main.py", *argv]):
        return parse_args()


def _preflight(argv: list[str]):
    return _run_preflight(_parse(argv))


class TestNonAllowlistTarget:
    def test_rejected_with_nonzero_exit(self):
        with pytest.raises(SystemExit) as exc:
            _preflight(["--target-ip", REJECTED])
        assert exc.value.code != 0

    def test_rejected_with_chinese_error(self, capsys):
        with pytest.raises(SystemExit):
            _preflight(["--target-ip", REJECTED])
        err = capsys.readouterr().err
        assert "allowlist" in err
        assert REJECTED in err
        assert "拒绝启动" in err


class TestBudgetValidation:
    def test_max_iters_zero_rejected(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _preflight(["--target-ip", ALLOWED, "--max-iters", "0"])
        assert exc.value.code != 0
        assert "max_iters" in capsys.readouterr().err

    def test_max_iters_negative_rejected(self, capsys):
        with pytest.raises(SystemExit):
            _preflight(["--target-ip", ALLOWED, "--max-iters", "-3"])
        assert "拒绝启动" in capsys.readouterr().err

    def test_no_improve_limit_negative_rejected(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _preflight(["--target-ip", ALLOWED, "--no-improve-limit", "-1"])
        assert exc.value.code != 0
        assert "no_improve_limit" in capsys.readouterr().err

    def test_no_improve_limit_zero_rejected(self, capsys):
        with pytest.raises(SystemExit):
            _preflight(["--target-ip", ALLOWED, "--no-improve-limit", "0"])
        assert "拒绝启动" in capsys.readouterr().err


class TestMutuallyExclusiveModes:
    def test_trex_explore_with_trex_live_aborts_at_startup(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _parse(["--trex-explore", "--trex-live"])
        assert exc.value.code != 0
        # 契约 §4：互斥组合启动即报错，stderr 输出中文原因
        err = capsys.readouterr().err
        assert "trex-explore" in err
        assert "互斥" in err


class TestCompliantParameters:
    def test_allowlisted_target_continues(self):
        assert _preflight(["--target-ip", ALLOWED, "--max-iters", "3"]) is None

    def test_defaults_continue(self):
        # 默认配置 target=100.1.11.20 ∈ allowlist，max_iters=20，limit=5
        assert _preflight([]) is None

    def test_catalog_mode_defaults_continue(self):
        args = _parse(["--trex-explore"])
        assert args.max_iters == 40  # catalog 默认（contracts §2）
        assert _run_preflight(args) is None

    def test_boundary_values_continue(self):
        assert _preflight(["--target-ip", ALLOWED,
                           "--max-iters", "1", "--no-improve-limit", "1"]) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
