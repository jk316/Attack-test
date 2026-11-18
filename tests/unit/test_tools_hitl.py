"""Unit tests for the HITL gates on src/agent/tools.py traffic tools (T010/T019).

T010: traffic_send 封装——审批拒绝 → 0 报文且不调用底层发送；env 默认解析与
内置回退。T019: mixed_traffic_send 封装——同样语义 + params_display 字段。
No real traffic: the underlying tool functions are mocked and interrupt() is
patched, so nothing can reach the network.
"""
from unittest.mock import patch

import pytest

from src.agent import tools as agent_tools

ALLOWLISTED_IP = "10.99.80.160"


def _traffic_call(**overrides):
    args = {"dst_ip": ALLOWLISTED_IP, "dst_port": 8080}
    args.update(overrides)
    return agent_tools.traffic_send.invoke(args)


class TestTrafficSendHitlGate:
    """T010：traffic_send 封装（FR-009/017、SC-003）。"""

    def test_rejected_returns_error_without_calling_underlying(self):
        with patch.object(agent_tools, "interrupt", return_value=False) as intr, \
             patch.object(agent_tools, "traffic_send_tool") as mock_tool:
            result = _traffic_call()

        assert result == {"success": False, "error": "HITL rejected by operator"}
        mock_tool.assert_not_called()  # 0 报文：底层发送未被调用

    def test_interrupt_payload_has_message_and_params(self):
        with patch.object(agent_tools, "interrupt", return_value=True) as intr, \
             patch.object(agent_tools, "traffic_send_tool",
                          return_value={"success": True}), \
             patch.object(agent_tools, "build_rtt_observation", return_value={}):
            _traffic_call(duration_s=3, pps=50)

        payload = intr.call_args[0][0]
        assert payload["message"] == "[HITL] Approve traffic send?"
        assert payload["params"]["dst_ip"] == ALLOWLISTED_IP
        assert payload["params"]["duration_s"] == 3
        assert payload["params"]["pps"] == 50

    def test_approved_calls_underlying_with_resolved_values(self):
        with patch.object(agent_tools, "interrupt", return_value=True), \
             patch.object(agent_tools, "traffic_send_tool",
                          return_value={"success": True}) as mock_tool, \
             patch.object(agent_tools, "build_rtt_observation", return_value={}):
            result = _traffic_call(duration_s=3, pps=50)

        assert result["success"] is True
        kwargs = mock_tool.call_args.kwargs
        assert kwargs["duration_s"] == 3
        assert kwargs["pps"] == 50

    def test_env_defaults_used_when_params_omitted(self, monkeypatch):
        monkeypatch.setenv("ATK_DURATION_S", "7")
        monkeypatch.setenv("ATK_PPS", "250")
        monkeypatch.setenv("ATK_PACKET_SIZE", "128")
        monkeypatch.setenv("ATK_FLOW_COUNT", "4")
        monkeypatch.setenv("ATK_IAT_JITTER_MS", "9")
        with patch.object(agent_tools, "interrupt", return_value=True), \
             patch.object(agent_tools, "traffic_send_tool",
                          return_value={"success": True}) as mock_tool, \
             patch.object(agent_tools, "build_rtt_observation", return_value={}):
            _traffic_call()

        kwargs = mock_tool.call_args.kwargs
        assert kwargs["duration_s"] == 7
        assert kwargs["pps"] == 250
        assert kwargs["packet_size"] == 128
        assert kwargs["flow_count"] == 4
        assert kwargs["iat_jitter_ms"] == 9

    def test_builtin_defaults_without_env(self, monkeypatch):
        for var in ("ATK_DURATION_S", "ATK_PPS", "ATK_PACKET_SIZE",
                    "ATK_FLOW_COUNT", "ATK_IAT_JITTER_MS"):
            monkeypatch.delenv(var, raising=False)
        with patch.object(agent_tools, "interrupt", return_value=True), \
             patch.object(agent_tools, "traffic_send_tool",
                          return_value={"success": True}) as mock_tool, \
             patch.object(agent_tools, "build_rtt_observation", return_value={}):
            _traffic_call()

        kwargs = mock_tool.call_args.kwargs
        assert kwargs["duration_s"] == 10
        assert kwargs["pps"] == 100
        assert kwargs["packet_size"] == 64
        assert kwargs["flow_count"] == 1
        assert kwargs["iat_jitter_ms"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestMixedTrafficSendHitlGate:
    """T019：mixed_traffic_send 封装（FR-009）。"""

    def _mixed_call(self, **overrides):
        spec = ('{"streams":[{"stream_id":"s1","protocol_stack":["IP","UDP"],'
                '"fields":{},"percentage":100}]}')
        args = {"dst_ip": ALLOWLISTED_IP, "traffic_spec_json": spec}
        args.update(overrides)
        return agent_tools.mixed_traffic_send.invoke(args)

    def test_rejected_zero_packets_no_underlying_call(self):
        with patch.object(agent_tools, "interrupt", return_value=False), \
             patch.object(agent_tools, "mixed_traffic_send_tool") as mock_tool:
            result = self._mixed_call()

        assert result == {"success": False, "error": "HITL rejected by operator"}
        mock_tool.assert_not_called()

    def test_params_display_has_required_fields(self):
        with patch.object(agent_tools, "interrupt", return_value=True) as intr, \
             patch.object(agent_tools, "mixed_traffic_send_tool",
                          return_value={"success": True}), \
             patch.object(agent_tools, "build_rtt_observation", return_value={}):
            self._mixed_call(duration_s=3, pps=50, iat_jitter_ms=5)

        payload = intr.call_args[0][0]
        assert payload["params"]["dst_ip"] == ALLOWLISTED_IP
        assert payload["params"]["duration_s"] == 3
        assert payload["params"]["pps"] == 50
        assert payload["params"]["iat_jitter_ms"] == 5

    def test_jitter_env_default_resolution(self, monkeypatch):
        monkeypatch.setenv("ATK_IAT_JITTER_MS", "6")
        with patch.object(agent_tools, "interrupt", return_value=True), \
             patch.object(agent_tools, "mixed_traffic_send_tool",
                          return_value={"success": True}) as mock_tool, \
             patch.object(agent_tools, "build_rtt_observation", return_value={}):
            self._mixed_call()

        kwargs = mock_tool.call_args.kwargs
        assert kwargs["iat_jitter_ms"] == 6
