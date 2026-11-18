"""validate_target 契约测试（008-T002）。

对照 contracts/allowlist-config.md 消费者契约与 data-model「目标校验」检查顺序：
allowlist 空 → "allowlist is empty"；非法格式 → "Invalid IP format"；
广播（.255）→ 拒绝；组播（224.0.0.0/4）→ 拒绝；非白名单 →
"Target … not in allowlist"；合法白名单 IP → 通过。
"""

import importlib

import pytest

# src/tools/__init__.py 将包属性 ping_rtt_tool 遮蔽为工具函数，模块须经 importlib 取
_PTT = importlib.import_module("src.tools.ping_rtt_tool")
validate_target = _PTT.validate_target


class TestValidateTargetContract:
    def test_allowlisted_ip_passes(self, monkeypatch):
        monkeypatch.setattr(_PTT, "ALLOWLIST", ["10.99.80.160"])
        validate_target("10.99.80.160")  # 不抛异常

    def test_non_allowlisted_ip_rejected(self, monkeypatch):
        monkeypatch.setattr(_PTT, "ALLOWLIST", ["10.99.80.160"])
        with pytest.raises(ValueError, match="not in allowlist"):
            validate_target("192.168.1.99")

    def test_empty_allowlist_rejected(self, monkeypatch):
        monkeypatch.setattr(_PTT, "ALLOWLIST", [])
        with pytest.raises(ValueError, match="allowlist is empty"):
            validate_target("10.99.80.160")

    def test_invalid_format_rejected(self, monkeypatch):
        monkeypatch.setattr(_PTT, "ALLOWLIST", ["10.99.80.160"])
        with pytest.raises(ValueError, match="Invalid IP format"):
            validate_target("999.999.999.999")

    def test_broadcast_rejected(self, monkeypatch):
        monkeypatch.setattr(_PTT, "ALLOWLIST", ["10.99.80.160"])
        with pytest.raises(ValueError, match="Broadcast"):
            validate_target("10.99.80.255")

    def test_multicast_rejected(self, monkeypatch):
        monkeypatch.setattr(_PTT, "ALLOWLIST", ["10.99.80.160"])
        with pytest.raises(ValueError, match="Multicast"):
            validate_target("224.0.0.1")

    def test_check_order_format_before_broadcast(self, monkeypatch):
        """非法格式优先于广播/组播检查（data-model 检查顺序）。"""
        monkeypatch.setattr(_PTT, "ALLOWLIST", ["10.99.80.160"])
        # 999.999.999.255 既非法又不是广播 —— 应报格式错误
        with pytest.raises(ValueError, match="Invalid IP format"):
            validate_target("999.999.999.255")
