"""Unit tests for src/agent/tools.py ping_rtt / log_result wrappers (T020).

FR-015/016 的 Agent 层契约：ping_rtt 透传底层返回；log_result 组装
{iteration, params, rtt, loss} 后调用 src/tools/log_tool.py::log_tool。
底层工具全部 mock——无 ping 子进程、无文件写入。
"""
from unittest.mock import patch

import pytest

from src.agent import tools as agent_tools

ALLOWLISTED_IP = "10.99.80.160"


class TestPingRttWrapper:
    def test_passes_through_underlying_result(self):
        mock_result = {
            "success": True, "avg_rtt_ms": 12.5, "loss_pct": 0.0,
            "packets_transmitted": 4, "packets_received": 4,
        }
        with patch.object(agent_tools, "ping_rtt_tool",
                          return_value=mock_result) as mock_tool:
            result = agent_tools.ping_rtt.invoke({
                "ip": ALLOWLISTED_IP, "count": 3, "timeout": 5,
            })

        assert result == mock_result  # 透传
        mock_tool.assert_called_once()
        kwargs = mock_tool.call_args.kwargs
        assert kwargs == {"ip": ALLOWLISTED_IP, "count": 3, "timeout": 5}

    def test_default_params(self):
        with patch.object(agent_tools, "ping_rtt_tool",
                          return_value={"success": True}) as mock_tool:
            agent_tools.ping_rtt.invoke({"ip": ALLOWLISTED_IP})

        kwargs = mock_tool.call_args.kwargs
        assert kwargs["count"] == 4
        assert kwargs["timeout"] == 10


class TestLogResultWrapper:
    def test_assembles_entry_and_calls_log_tool(self):
        params = {"pps": 100, "duration_s": 5}
        with patch.object(agent_tools, "log_tool",
                          return_value={"success": True}) as mock_tool:
            result = agent_tools.log_result.invoke({
                "log_path": "data/x.jsonl",
                "iteration": 3,
                "params": params,
                "rtt": 12.5,
                "loss": 2.0,
            })

        assert result == {"success": True}
        mock_tool.assert_called_once()
        args, kwargs = mock_tool.call_args
        assert kwargs == {"log_path": "data/x.jsonl",
                          "entry": {"iteration": 3, "params": params,
                                    "rtt": 12.5, "loss": 2.0}}

    def test_entry_content_matches_wrapper_doc(self):
        with patch.object(agent_tools, "log_tool",
                          return_value={"success": True}) as mock_tool:
            agent_tools.log_result.invoke({
                "log_path": "data/x.jsonl",
                "iteration": 0,
                "params": {"pps": 50},
                "rtt": 30.0,
                "loss": 0.0,
            })

        entry = mock_tool.call_args.kwargs["entry"]
        assert entry == {"iteration": 0, "params": {"pps": 50},
                         "rtt": 30.0, "loss": 0.0}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
