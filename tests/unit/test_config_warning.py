"""配置默认值超限启动警告测试（008-T011）。

008-2 决议：main.py 加载 experiment.json 后逐项比对默认值与宪法上限，
超限项输出 WARN 且包含「字段/配置值/钳制后上限值」三要素，进程正常继续
（不报错退出）。钳制仍在工具内执行，本层只负责可见性。
"""

import sys
from unittest.mock import patch

import pytest

from src.main import _warn_config_over_limits


def _args(**overrides):
    import argparse
    base = dict(
        pps=100, duration=10, packet_size=64, flow_count=1,
        iat_jitter_ms=0, pktgen_rate=50, pktgen_duration=10000,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


class TestConfigWarning:
    def test_over_limit_pps_warns_with_triple(self, capsys):
        _warn_config_over_limits(_args(pps=99999))
        err = capsys.readouterr().err
        assert "[配置警告]" in err
        assert "attack.pps" in err          # 字段
        assert "99999" in err               # 配置值
        assert "20000" in err               # 钳制后上限值

    def test_over_limit_pktgen_duration_warns(self, capsys):
        _warn_config_over_limits(_args(pktgen_duration=120000))
        err = capsys.readouterr().err
        assert "pktgen.duration_ms" in err
        assert "120000" in err
        assert "60000" in err

    def test_over_limit_pktgen_rate_warns(self, capsys):
        _warn_config_over_limits(_args(pktgen_rate=150))
        err = capsys.readouterr().err
        assert "pktgen.rate" in err
        assert "150" in err
        assert "100" in err

    @pytest.mark.parametrize("field,value,limit", [
        ("duration", 25, 20),
        ("packet_size", 2048, 1024),
        ("flow_count", 500, 100),
        ("iat_jitter_ms", 30, 20),
    ])
    def test_attack_fields_warn(self, capsys, field, value, limit):
        _warn_config_over_limits(_args(**{field: value}))
        err = capsys.readouterr().err
        assert f"attack.{field}" in err
        assert str(value) in err
        assert str(limit) in err

    def test_within_limits_silent(self, capsys):
        _warn_config_over_limits(_args())
        assert capsys.readouterr().err == ""

    def test_boundary_values_silent(self, capsys):
        _warn_config_over_limits(_args(
            pps=20000, duration=20, packet_size=1024, flow_count=100,
            iat_jitter_ms=20, pktgen_rate=100, pktgen_duration=60000,
        ))
        assert capsys.readouterr().err == ""

    def test_main_calls_warning_layer(self, monkeypatch, capsys):
        """main() 在 env 注入前调用告警层（不因告警退出）。"""
        import src.main as main_mod

        called = {}

        def fake_warn(args):
            called["args"] = args

        monkeypatch.setattr(main_mod, "_warn_config_over_limits", fake_warn)
        # 让 main() 在 preflight 后立即退出：以非 allowlist 目标触发预检失败，
        # 验证告警层调用顺序在预检之后（预检失败即退出 → 告警不应被调用）
        with patch.object(sys, "argv", ["main.py", "--target-ip", "192.168.1.99"]):
            with pytest.raises(SystemExit):
                main_mod.main()
        assert "args" not in called  # 预检失败先退出，告警层不执行

        # 合法目标 + 超限参数：预检通过 → 告警层被调用
        with patch.object(sys, "argv", ["main.py", "--target-ip", "10.99.80.160",
                                        "--pps", "99999"]):
            try:
                main_mod.main()
            except SystemExit:
                pass
            except Exception:
                # 后续 LLM/图构建失败不影响本断言
                pass
        assert "args" in called
