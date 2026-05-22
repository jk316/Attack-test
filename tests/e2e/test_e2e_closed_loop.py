"""End-to-end tests for the create_agent-based closed-loop experiment agent."""
from unittest.mock import MagicMock, patch, call
import pytest
from langgraph.types import Command
from langchain_core.messages import AIMessage, HumanMessage


def _make_ai_with_tool_calls(*tool_calls: dict) -> AIMessage:
    """Build an AIMessage with mock tool calls."""
    formatted = []
    for i, tc in enumerate(tool_calls):
        formatted.append({
            "name": tc["name"],
            "args": tc.get("args", {}),
            "id": tc.get("id", f"call_{i}"),
        })
    return AIMessage(content="", tool_calls=formatted)


def _make_final(content: str = "Experiment complete.") -> AIMessage:
    """Build a final AIMessage without tool calls."""
    return AIMessage(content=content, tool_calls=[])


def _build_mock_model(responses: list[AIMessage]) -> MagicMock:
    """Create a mock ChatOpenAI that returns the given responses in order."""
    model = MagicMock()
    model.model_name = "deepseek-chat"
    model.bind_tools.return_value = model
    model.invoke.side_effect = responses
    return model


class TestFullClosedLoop:
    """End-to-end tests of the complete experiment loop."""

    def test_agent_runs_full_iteration_sequence(self):
        """Agent should execute traffic_send → ping_rtt → log_result → final response."""
        from src.agent.graph import build_graph

        model = _build_mock_model([
            # Iteration 1: send traffic
            _make_ai_with_tool_calls(
                {"name": "traffic_send", "args": {
                    "dst_ip": "10.99.80.160", "dst_port": 8080, "pps": 50,
                }, "id": "c1"},
            ),
            # measure rtt
            _make_ai_with_tool_calls(
                {"name": "ping_rtt", "args": {"ip": "10.99.80.160"}, "id": "c2"},
            ),
            # log result
            _make_ai_with_tool_calls(
                {"name": "log_result", "args": {
                    "log_path": "data/e2e_test.jsonl", "iteration": 0,
                    "params": {"pps": 50}, "rtt": 30.0, "loss": 0.0,
                }, "id": "c3"},
            ),
            # agent decides to continue or stop
            _make_final("Iteration 1 done. RTT=30ms, loss=0%. Continuing..."),
        ])

        with patch("src.agent.graph._build_model", return_value=model), \
             patch("src.agent.tools.traffic_send_tool") as mock_send, \
             patch("src.agent.tools.ping_rtt_tool") as mock_ping, \
             patch("src.agent.tools.log_tool") as mock_log, \
             patch("src.agent.tools.interrupt", return_value=True):

            mock_send.return_value = {"success": True, "packets_sent": {"total": 250}}
            mock_ping.return_value = {"success": True, "avg_rtt_ms": 30.0, "loss_pct": 0.0}
            mock_log.return_value = {"success": True}

            graph = build_graph()
            config = {"configurable": {"thread_id": "e2e-full"}}
            result = graph.invoke(
                {"messages": [HumanMessage(content="Run experiment iteration 0")]},
                config,
            )

        # All three tools called in order
        mock_send.assert_called_once()
        mock_ping.assert_called_once()
        mock_log.assert_called_once()
        assert "Iteration 1 done" in result["messages"][-1].content

    def test_agent_runs_multiple_iterations(self):
        """Agent should handle multiple iterations of the experiment loop."""
        from src.agent.graph import build_graph

        # Simulate 3 full iterations
        responses = []
        for i in range(3):
            responses.append(_make_ai_with_tool_calls(
                {"name": "traffic_send", "args": {
                    "dst_ip": "10.99.80.160", "dst_port": 8080,
                    "pps": 50 + i * 10,
                }, "id": f"send_{i}"},
            ))
            responses.append(_make_ai_with_tool_calls(
                {"name": "ping_rtt", "args": {"ip": "10.99.80.160"}, "id": f"ping_{i}"},
            ))
            responses.append(_make_ai_with_tool_calls(
                {"name": "log_result", "args": {
                    "log_path": "data/e2e_test.jsonl", "iteration": i,
                    "params": {"pps": 50 + i * 10}, "rtt": 30.0 + i * 5, "loss": 0.0,
                }, "id": f"log_{i}"},
            ))
        responses.append(_make_final("Experiment complete after 3 iterations."))

        model = _build_mock_model(responses)

        with patch("src.agent.graph._build_model", return_value=model), \
             patch("src.agent.tools.traffic_send_tool") as mock_send, \
             patch("src.agent.tools.ping_rtt_tool") as mock_ping, \
             patch("src.agent.tools.log_tool") as mock_log, \
             patch("src.agent.tools.interrupt", return_value=True):

            mock_send.return_value = {"success": True, "packets_sent": {"total": 250}}
            mock_ping.return_value = {"success": True, "avg_rtt_ms": 30.0, "loss_pct": 0.0}
            mock_log.return_value = {"success": True}

            graph = build_graph()
            config = {"configurable": {"thread_id": "e2e-multi"}}
            result = graph.invoke(
                {"messages": [HumanMessage(content="Run experiment for 3 iterations")]},
                config,
            )

        assert mock_send.call_count == 3
        assert mock_ping.call_count == 3
        assert mock_log.call_count == 3
        assert "3 iterations" in result["messages"][-1].content

    def test_agent_stops_when_model_decides(self):
        """When model returns final response (no tool_calls), the agent stops."""
        from src.agent.graph import build_graph

        model = _build_mock_model([
            _make_final("No more improvements possible. Stopping experiment."),
        ])

        with patch("src.agent.graph._build_model", return_value=model):
            graph = build_graph()
            config = {"configurable": {"thread_id": "e2e-stop"}}
            result = graph.invoke(
                {"messages": [HumanMessage(content="Start experiment")]},
                config,
            )

        assert "No more improvements" in result["messages"][-1].content


class TestHITLResume:
    """E2E tests for HITL interrupt/resume flow with create_agent."""

    def test_hitl_interrupts_and_resumes(self):
        """Graph interrupts at traffic_send, resumes with Command(resume=True)."""
        from src.agent.graph import build_graph

        model = _build_mock_model([
            _make_ai_with_tool_calls(
                {"name": "traffic_send", "args": {
                    "dst_ip": "10.99.80.160", "dst_port": 8080, "pps": 50,
                }, "id": "c1"},
            ),
            _make_ai_with_tool_calls(
                {"name": "ping_rtt", "args": {"ip": "10.99.80.160"}, "id": "c2"},
            ),
            _make_final("Traffic sent and measured."),
        ])

        with patch("src.agent.graph._build_model", return_value=model), \
             patch("src.agent.tools.traffic_send_tool") as mock_send, \
             patch("src.agent.tools.ping_rtt_tool") as mock_ping, \
             patch("src.agent.tools.interrupt", return_value=True):

            mock_send.return_value = {"success": True, "packets_sent": {"total": 250}}
            mock_ping.return_value = {"success": True, "avg_rtt_ms": 30.0, "loss_pct": 0.0}

            graph = build_graph()
            config = {"configurable": {"thread_id": "e2e-hitl"}}
            state = {"messages": [HumanMessage(content="Send traffic then measure")]}

            # Invoke — will pass through HITL with interrupt returning True
            result = graph.invoke(state, config)

        mock_send.assert_called_once()
        assert "Traffic sent" in result["messages"][-1].content

    def test_hitl_rejected_continues(self):
        """When HITL rejects, agent receives error and can adapt."""
        from src.agent.graph import build_graph

        model = _build_mock_model([
            _make_ai_with_tool_calls(
                {"name": "traffic_send", "args": {
                    "dst_ip": "10.99.80.160", "dst_port": 8080, "pps": 100,
                }, "id": "c1"},
            ),
            _make_final("Traffic was rejected by operator. Cannot proceed."),
        ])

        with patch("src.agent.graph._build_model", return_value=model), \
             patch("src.agent.tools.traffic_send_tool") as mock_send, \
             patch("src.agent.tools.interrupt", return_value=False):

            graph = build_graph()
            config = {"configurable": {"thread_id": "e2e-hitl-reject"}}
            result = graph.invoke(
                {"messages": [HumanMessage(content="Send test traffic")]},
                config,
            )

        # traffic_send_tool should NOT be called (HITL rejected)
        mock_send.assert_not_called()
        assert "rejected" in result["messages"][-1].content.lower()


class TestToolErrorHandling:
    """Verify the agent handles tool errors gracefully."""

    def test_ping_error_returns_to_agent(self):
        """When ping fails, the error is returned to the agent for handling."""
        from src.agent.graph import build_graph

        model = _build_mock_model([
            _make_ai_with_tool_calls(
                {"name": "ping_rtt", "args": {"ip": "10.99.80.160"}, "id": "c1"},
            ),
            _make_final("Ping failed. Agent will adjust strategy."),
        ])

        with patch("src.agent.graph._build_model", return_value=model), \
             patch("src.agent.tools.ping_rtt_tool") as mock_ping:
            mock_ping.return_value = {
                "success": False, "error": "Network unreachable",
            }

            graph = build_graph()
            config = {"configurable": {"thread_id": "e2e-error"}}
            result = graph.invoke(
                {"messages": [HumanMessage(content="Measure RTT")]},
                config,
            )

        mock_ping.assert_called_once()
        assert "adjust" in result["messages"][-1].content.lower()

    def test_non_allowlist_ip_bubbles_error(self):
        """Tool validates IP and raises ValueError for non-allowlist targets."""
        from src.agent.graph import build_graph

        model = _build_mock_model([
            _make_ai_with_tool_calls(
                {"name": "ping_rtt", "args": {"ip": "192.168.1.99"}, "id": "c1"},
            ),
        ])

        with patch("src.agent.graph._build_model", return_value=model):
            graph = build_graph()
            config = {"configurable": {"thread_id": "e2e-reject"}}

            # The ping_rtt_tool raises ValueError for non-allowlist IP.
            # create_agent propagates tool errors by default.
            with pytest.raises(ValueError, match="not in allowlist"):
                graph.invoke(
                    {"messages": [HumanMessage(content="Ping 192.168.1.99")]},
                    config,
                )


class TestPCAPIntegration:
    """Verify PCAP profiling integrates correctly in the agent flow."""

    def test_pcap_profile_before_traffic(self):
        """Agent profiles PCAP first, uses results to inform traffic params."""
        from src.agent.graph import build_graph

        mock_profile = {
            "top_dst_ports": [28763],
            "packet_size_hist": {"64": 0.97},
            "iat_ms_stats": {"mean": 25.0, "p50": 20.0, "p90": 40.0},
            "flow_stats": {"approx_flow_count": 4, "timeout_s": 30},
        }

        model = _build_mock_model([
            # Step 1: profile PCAP
            _make_ai_with_tool_calls(
                {"name": "pcap_profile", "args": {"pcap_path": "data/game.pcapng"}, "id": "c1"},
            ),
            # Step 2: send traffic using profile data (port 28763 from PCAP)
            _make_ai_with_tool_calls(
                {"name": "traffic_send", "args": {
                    "dst_ip": "10.99.80.160", "dst_port": 28763, "pps": 50,
                    "packet_size": 64, "flow_count": 2,
                }, "id": "c2"},
            ),
            _make_ai_with_tool_calls(
                {"name": "ping_rtt", "args": {"ip": "10.99.80.160"}, "id": "c3"},
            ),
            _make_final("Experiment initialized from PCAP profile."),
        ])

        with patch("src.agent.graph._build_model", return_value=model), \
             patch("src.agent.tools.pcap_profile_tool") as mock_profile_fn, \
             patch("src.agent.tools.traffic_send_tool") as mock_send, \
             patch("src.agent.tools.ping_rtt_tool") as mock_ping, \
             patch("src.agent.tools.interrupt", return_value=True):

            mock_profile_fn.return_value = mock_profile
            mock_send.return_value = {"success": True}
            mock_ping.return_value = {"success": True, "avg_rtt_ms": 30.0, "loss_pct": 0.0}

            graph = build_graph()
            config = {"configurable": {"thread_id": "e2e-pcap"}}
            result = graph.invoke(
                {"messages": [HumanMessage(content="Profile data/game.pcapng and start experiment")]},
                config,
            )

        mock_profile_fn.assert_called_once()
        mock_send.assert_called_once()
        # Verify traffic_send was called with port from PCAP profile
        assert mock_send.call_args.kwargs["dst_port"] == 28763
        assert "PCAP" in result["messages"][-1].content
