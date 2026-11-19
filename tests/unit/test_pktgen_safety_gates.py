"""Pktgen 安全门控测试 — G1（duration 上限拒绝）/ G3（src_ip 禁止）/ D9（合法源注入）。

005-US1 失败测试（TDD 红-绿）：当前实现尚未拒绝 duration>60000ms 与 LLM
传入 src_ip，也未把 PKTGEN_SRC_IP 注入的合法源填入编译参数覆盖 vendored
默认伪造源 192.168.1.1/24。全部用例 mock 网络 I/O（零流量、零硬件连接）。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

ALLOWLISTED_IP = "10.99.80.160"
CONFIGURED_SRC_IP = "10.99.80.10/24"  # 005-T004 experiment.json pktgen.src_ip 默认


def _invoke(tool, params: dict):
    """调用工具并返回结果；确保 dry-run（HITL 跳过）与网络无关。"""
    return tool.invoke(params)


# ── G1: duration > 60000 ms 拒绝 ──────────────────────────────────────

class TestDurationLimit:
    """G1：duration 上限 60000ms，超限拒绝且零编译零流量。"""

    @pytest.mark.parametrize("tool_name", [
        "pktgen_udp_flood", "pktgen_tcp_flood", "pktgen_icmp_flood", "pktgen_arp_flood",
    ])
    def test_duration_over_60000_rejected(self, tool_name):
        """duration=120000 被拒绝：success=false、参数错误、执行器零调用。"""
        from src.pktgen import adapter

        tool = getattr(adapter, tool_name)
        params = {"rate": 50, "duration": 120000}
        if tool_name != "pktgen_arp_flood":
            params["dst_ip"] = ALLOWLISTED_IP

        with patch.object(adapter, "_execute_skill") as mock_exec:
            mock_exec.return_value = {"success": True, "mode": "dry_run"}
            result = _invoke(tool, params)

        assert result["success"] is False
        assert "60000" in str(result["error"]) or "duration" in str(result["error"]).lower()
        assert result["mode"] == "unknown"
        mock_exec.assert_not_called()  # 零编译零流量

    @pytest.mark.parametrize("tool_name", [
        "pktgen_udp_flood", "pktgen_tcp_flood", "pktgen_icmp_flood", "pktgen_arp_flood",
    ])
    def test_duration_at_limit_allowed(self, tool_name):
        """duration=60000（边界）合法：正常执行。"""
        from src.pktgen import adapter

        tool = getattr(adapter, tool_name)
        params = {"rate": 50, "duration": 60000}
        if tool_name != "pktgen_arp_flood":
            params["dst_ip"] = ALLOWLISTED_IP

        with patch.object(adapter, "_execute_skill") as mock_exec:
            mock_exec.return_value = {"success": True, "mode": "dry_run"}
            result = _invoke(tool, params)

        assert result["success"] is True
        mock_exec.assert_called_once()

    def test_duration_zero_forever_allowed(self):
        """duration=0（永久发包语义）合法：正常执行（由 stop_and_reset 终止）。"""
        from src.pktgen import adapter
        from src.pktgen.adapter import pktgen_udp_flood

        with patch.object(adapter, "_execute_skill") as mock_exec:
            mock_exec.return_value = {"success": True, "mode": "dry_run"}
            result = _invoke(pktgen_udp_flood, {"dst_ip": ALLOWLISTED_IP, "rate": 50, "duration": 0})

        assert result["success"] is True
        mock_exec.assert_called_once()


# ── G3: src_ip 禁止自定义 ────────────────────────────────────────────

class TestSrcIpForbidden:
    """G3：LLM 传入 src_ip（非省略）被拒绝；合法源仅来自配置。"""

    @pytest.mark.parametrize("tool_name", [
        "pktgen_udp_flood", "pktgen_tcp_flood", "pktgen_icmp_flood",
    ])
    def test_explicit_src_ip_rejected(self, tool_name):
        """传入 src_ip 被拒绝：success=false、错误说明、执行器零调用。"""
        from src.pktgen import adapter

        tool = getattr(adapter, tool_name)
        with patch.object(adapter, "_execute_skill") as mock_exec:
            mock_exec.return_value = {"success": True, "mode": "dry_run"}
            result = _invoke(tool, {
                "dst_ip": ALLOWLISTED_IP, "rate": 50,
                "src_ip": "10.0.0.1/24",
            })

        assert result["success"] is False
        assert "src_ip" in str(result["error"]).lower()
        mock_exec.assert_not_called()


# ── D9: PKTGEN_SRC_IP 合法源注入 ─────────────────────────────────────

class TestConfiguredSrcIpInjection:
    """D9：未传 src_ip 时，编译参数采用 PKTGEN_SRC_IP 注入的合法源。"""

    @pytest.mark.parametrize("tool_name", [
        "pktgen_udp_flood", "pktgen_tcp_flood", "pktgen_icmp_flood",
    ])
    def test_env_src_ip_injected(self, tool_name, monkeypatch):
        """env PKTGEN_SRC_IP 设置的合法源进入编译参数，覆盖 vendored 默认。"""
        from src.pktgen import adapter

        monkeypatch.setenv("PKTGEN_SRC_IP", CONFIGURED_SRC_IP)
        tool = getattr(adapter, tool_name)
        with patch.object(adapter, "_execute_skill") as mock_exec:
            mock_exec.return_value = {"success": True, "mode": "dry_run"}
            _invoke(tool, {"dst_ip": ALLOWLISTED_IP, "rate": 50})

        _, params = mock_exec.call_args[0]
        assert params["src_ip"] == CONFIGURED_SRC_IP

    @pytest.mark.parametrize("tool_name", [
        "pktgen_udp_flood", "pktgen_tcp_flood", "pktgen_icmp_flood",
    ])
    def test_config_default_fallback_injected(self, tool_name, monkeypatch):
        """env 缺失时回退 T004 配置默认（10.99.80.10/24），不落回 vendored 伪造源。"""
        from src.pktgen import adapter

        monkeypatch.delenv("PKTGEN_SRC_IP", raising=False)
        tool = getattr(adapter, tool_name)
        with patch.object(adapter, "_execute_skill") as mock_exec:
            mock_exec.return_value = {"success": True, "mode": "dry_run"}
            _invoke(tool, {"dst_ip": ALLOWLISTED_IP, "rate": 50})

        _, params = mock_exec.call_args[0]
        assert params["src_ip"] == CONFIGURED_SRC_IP
        assert params["src_ip"] != "192.168.1.1/24"  # vendored 伪造默认被覆盖

    def test_arp_flood_untouched_by_src_ip_policy(self, monkeypatch):
        """arp_flood 无 src_ip 参数：不注入、也不因 env 存在而报错。"""
        from src.pktgen import adapter
        from src.pktgen.adapter import pktgen_arp_flood

        monkeypatch.setenv("PKTGEN_SRC_IP", CONFIGURED_SRC_IP)
        with patch.object(adapter, "_execute_skill") as mock_exec:
            mock_exec.return_value = {"success": True, "mode": "dry_run"}
            result = _invoke(pktgen_arp_flood, {"rate": 50})

        assert result["success"] is True
        _, params = mock_exec.call_args[0]
        assert "src_ip" not in params
