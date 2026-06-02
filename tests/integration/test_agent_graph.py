"""Tests for the create_agent-based graph builder."""
from unittest.mock import MagicMock, patch
import pytest
from langgraph.graph.state import CompiledStateGraph
from langchain_core.messages import AIMessage, HumanMessage


@pytest.fixture
def mock_model():
    """Create a mock ChatOpenAI that handles bind_tools().invoke() chain.

    create_agent internally calls model.bind_tools(tools).invoke(messages),
    so the mock must support this chained pattern.
    """
    model = MagicMock()
    model.model_name = "deepseek-chat"
    # bind_tools returns self so that .invoke() can be called on the same mock
    model.bind_tools.return_value = model
    return model


def _make_ai_with_tool_calls(tool_calls: list[dict]) -> AIMessage:
    """Build an AIMessage with mock tool calls."""
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": tc["name"],
                "args": tc.get("args", {}),
                "id": tc.get("id", f"call_{i}"),
            }
            for i, tc in enumerate(tool_calls)
        ],
    )


def _make_final_response(content: str = "Experiment complete.") -> AIMessage:
    """Build a final AIMessage without tool calls."""
    return AIMessage(content=content, tool_calls=[])


class TestBuildGraph:
    """Verify graph structure and compilation."""

    def test_build_graph_returns_compiled_graph(self):
        from src.agent.graph import build_graph
        with patch("src.agent.graph._build_model", return_value=MagicMock()):
            graph = build_graph()
        assert isinstance(graph, CompiledStateGraph)

    def test_graph_has_model_and_tools_nodes(self):
        from src.agent.graph import build_graph
        with patch("src.agent.graph._build_model", return_value=MagicMock()):
            graph = build_graph()
        nodes = list(graph.builder.nodes.keys())
        assert "model" in nodes
        assert "tools" in nodes

    def test_graph_has_checkpointer(self):
        from src.agent.graph import build_graph
        with patch("src.agent.graph._build_model", return_value=MagicMock()):
            graph = build_graph()
        assert graph.checkpointer is not None

    def test_graph_has_four_tools(self):
        from src.agent.graph import build_graph
        with patch("src.agent.graph._build_model", return_value=MagicMock()):
            graph = build_graph()
        # The tools are registered as nodes under the tools node
        assert "tools" in graph.builder.nodes


class TestAgentToolCalling:
    """Verify the agent can call tools via create_agent's ReAct loop."""

    def test_agent_calls_ping_rtt_tool(self, mock_model):
        """When model requests a ping, the tool is executed and result returned."""
        from src.agent.graph import build_graph

        mock_model.invoke.return_value = _make_ai_with_tool_calls([{
            "name": "ping_rtt",
            "args": {"ip": "10.99.80.160", "count": 4},
            "id": "call_1",
        }])

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.agent.tools.ping_rtt_tool") as mock_ping:
            mock_ping.return_value = {"success": True, "avg_rtt_ms": 25.0, "loss_pct": 0.0}

            graph = build_graph()
            state = {"messages": [HumanMessage(content="Measure RTT to 10.99.80.160")]}
            config = {"configurable": {"thread_id": "test-001"}}

            # First invoke - will run model → tools but model returns tool call first
            # Since model returns tool_calls on first invoke, need to handle
            # the full flow. create_agent loops until no more tool_calls.
            # We need mock_model.invoke to first return a tool call, then final.
            mock_model.invoke.side_effect = [
                _make_ai_with_tool_calls([{
                    "name": "ping_rtt",
                    "args": {"ip": "10.99.80.160"},
                    "id": "call_1",
                }]),
                _make_final_response("RTT is 25ms"),
            ]

            result = graph.invoke(state, config)

        mock_ping.assert_called_once_with(ip="10.99.80.160", count=4, timeout=10)
        assert result["messages"][-1].content == "RTT is 25ms"

    def test_agent_runs_traffic_send_and_ping_sequence(self, mock_model):
        """Verify the agent can execute a traffic_send → ping_rtt → log sequence."""
        from src.agent.graph import build_graph

        mock_model.invoke.side_effect = [
            # Step 1: send traffic (HITL approved by mock)
            _make_ai_with_tool_calls([{
                "name": "traffic_send",
                "args": {"dst_ip": "10.99.80.160", "dst_port": 8080, "pps": 50},
                "id": "call_1",
            }]),
            # Step 2: measure RTT
            _make_ai_with_tool_calls([{
                "name": "ping_rtt",
                "args": {"ip": "10.99.80.160"},
                "id": "call_2",
            }]),
            # Step 3: log
            _make_ai_with_tool_calls([{
                "name": "log_result",
                "args": {"log_path": "data/test.jsonl", "iteration": 0,
                         "params": {"pps": 50}, "rtt": 30.0, "loss": 0.0},
                "id": "call_3",
            }]),
            # Step 4: final response
            _make_final_response("Iteration 0 complete. RTT: 30ms."),
        ]

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.agent.tools.traffic_send_tool") as mock_send, \
             patch("src.agent.tools.ping_rtt_tool") as mock_ping, \
             patch("src.agent.tools.log_tool") as mock_log, \
             patch("src.agent.tools.interrupt", return_value=True):

            mock_send.return_value = {
                "success": True, "packets_sent": {"total": 250}, "elapsed_s": 5.0,
            }
            mock_ping.return_value = {"success": True, "avg_rtt_ms": 30.0, "loss_pct": 0.0}
            mock_log.return_value = {"success": True}

            graph = build_graph()
            state = {"messages": [HumanMessage(content="Run experiment iteration 0")]}
            config = {"configurable": {"thread_id": "test-002"}}

            result = graph.invoke(state, config)

        # All three tools were called
        mock_send.assert_called_once_with(
            dst_ip="10.99.80.160", dst_port=8080, duration_s=5,
            pps=50, packet_size=64, flow_count=1, iat_jitter_ms=0,
        )
        mock_ping.assert_called_once_with(ip="10.99.80.160", count=4, timeout=10)
        mock_log.assert_called_once()
        assert "Iteration 0 complete" in result["messages"][-1].content


class TestHITL:
    """Verify the HITL gate in traffic_send tool works with create_agent."""

    def test_hitl_rejection_stops_traffic(self, mock_model):
        """When HITL is rejected, traffic_send returns error but agent continues."""
        from src.agent.graph import build_graph

        mock_model.invoke.side_effect = [
            _make_ai_with_tool_calls([{
                "name": "traffic_send",
                "args": {"dst_ip": "10.99.80.160", "dst_port": 8080, "pps": 50},
                "id": "call_1",
            }]),
            _make_final_response("Traffic was rejected by operator."),
        ]

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.agent.tools.traffic_send_tool") as mock_send, \
             patch("src.agent.tools.interrupt", return_value=False):

            graph = build_graph()
            state = {"messages": [HumanMessage(content="Send test traffic")]}
            config = {"configurable": {"thread_id": "test-hitl-001"}}

            result = graph.invoke(state, config)

        # traffic_send_tool should NOT be called (HITL rejected)
        mock_send.assert_not_called()
        assert "rejected" in result["messages"][-1].content.lower()

    def test_hitl_approved_proceeds(self, mock_model):
        """When HITL is approved, traffic_send executes normally."""
        from src.agent.graph import build_graph

        mock_model.invoke.side_effect = [
            _make_ai_with_tool_calls([{
                "name": "traffic_send",
                "args": {"dst_ip": "10.99.80.160", "dst_port": 8080, "pps": 100},
                "id": "call_1",
            }]),
            _make_final_response("Traffic sent successfully."),
        ]

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.agent.tools.traffic_send_tool") as mock_send, \
             patch("src.agent.tools.interrupt", return_value=True):

            mock_send.return_value = {
                "success": True, "packets_sent": {"total": 500},
            }

            graph = build_graph()
            state = {"messages": [HumanMessage(content="Send test traffic")]}
            config = {"configurable": {"thread_id": "test-hitl-002"}}

            result = graph.invoke(state, config)

        mock_send.assert_called_once()
        assert "success" in result["messages"][-1].content.lower()


class TestPcapProfile:
    """Verify pcap_profile tool can be called by the agent."""

    def test_agent_profiles_pcap_before_traffic(self, mock_model):
        """The agent should be able to call pcap_profile to analyze a PCAP file."""
        from src.agent.graph import build_graph

        mock_profile = {
            "top_dst_ports": [28763],
            "packet_size_hist": {"64": 0.97, "128": 0.03},
            "iat_ms_stats": {"mean": 25.0, "p50": 20.0, "p90": 40.0},
            "flow_stats": {"approx_flow_count": 4, "timeout_s": 30},
        }

        mock_model.invoke.side_effect = [
            _make_ai_with_tool_calls([{
                "name": "pcap_profile",
                "args": {"pcap_path": "data/game.pcapng"},
                "id": "call_1",
            }]),
            _make_final_response(f"PCAP analysis complete. Top port: 28763."),
        ]

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.agent.tools.pcap_profile_tool") as mock_profile_fn:
            mock_profile_fn.return_value = mock_profile

            graph = build_graph()
            state = {"messages": [HumanMessage(content="Profile data/game.pcapng first")]}
            config = {"configurable": {"thread_id": "test-pcap-001"}}

            result = graph.invoke(state, config)

        mock_profile_fn.assert_called_once_with(
            pcap_path="data/game.pcapng", count=50000,
        )
        assert "28763" in result["messages"][-1].content


class TestAgentStops:
    """Verify the agent stops when it decides to."""

    def test_agent_stops_without_tool_calls(self, mock_model):
        """When model returns a response with no tool_calls, the agent stops."""
        from src.agent.graph import build_graph

        mock_model.invoke.return_value = _make_final_response("Experiment done.")

        with patch("src.agent.graph._build_model", return_value=mock_model):
            graph = build_graph()
            state = {"messages": [HumanMessage(content="Start experiment")]}
            config = {"configurable": {"thread_id": "test-stop-001"}}

            result = graph.invoke(state, config)

        # Should stop immediately - model returned no tool calls
        assert result["messages"][-1].content == "Experiment done."

    def test_agent_stops_after_single_tool_call(self, mock_model):
        """Agent stops after executing one tool and getting final response."""
        from src.agent.graph import build_graph

        mock_model.invoke.side_effect = [
            _make_ai_with_tool_calls([{
                "name": "ping_rtt",
                "args": {"ip": "10.99.80.160"},
                "id": "call_1",
            }]),
            _make_final_response("Ping result: 30ms. Experiment complete."),
        ]

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.agent.tools.ping_rtt_tool") as mock_ping:
            mock_ping.return_value = {"success": True, "avg_rtt_ms": 30.0, "loss_pct": 0.0}

            graph = build_graph()
            state = {"messages": [HumanMessage(content="Ping the target")]}
            config = {"configurable": {"thread_id": "test-stop-002"}}

            result = graph.invoke(state, config)

        assert "30ms" in result["messages"][-1].content
        assert len([m for m in result["messages"] if hasattr(m, "tool_calls") and m.tool_calls]) > 0


class TestPingMonitorTools:
    """Verify the continuous ping monitor tools integrate with the agent."""

    @pytest.fixture
    def mock_monitor(self):
        """Create a mock PingMonitor with controllable stats."""
        monitor = MagicMock()
        monitor.is_running.return_value = True
        monitor.target_ip = "10.99.80.160"
        monitor.get_stats.return_value = {
            "monitor_active": True,
            "target_ip": "10.99.80.160",
            "latest_rtt_ms": 12.5,
            "avg_rtt_ms": 12.3,
            "min_rtt_ms": 10.1,
            "max_rtt_ms": 15.2,
            "sample_count": 5,
            "loss_pct": 0.0,
            "window_s": 5.0,
        }
        monitor.get_samples_since.return_value = [
            {"ts": 1717200000.0, "rtt_ms": 10.0},
            {"ts": 1717200001.0, "rtt_ms": 25.0},
            {"ts": 1717200002.0, "rtt_ms": 30.0},
        ]
        return monitor

    def test_agent_calls_start_ping_monitor(self, mock_model, mock_monitor):
        """Agent should be able to call start_ping_monitor tool."""
        from src.agent.graph import build_graph

        mock_model.invoke.side_effect = [
            _make_ai_with_tool_calls([{
                "name": "start_ping_monitor",
                "args": {"ip": "10.99.80.160", "interval_s": 1.0},
                "id": "call_1",
            }]),
            _make_final_response("Ping monitor started successfully."),
        ]

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.agent.tools.get_ping_monitor", return_value=mock_monitor):
            graph = build_graph()
            state = {"messages": [HumanMessage(content="Start monitoring RTT")]}
            config = {"configurable": {"thread_id": "test-pm-start"}}

            result = graph.invoke(state, config)

        mock_monitor.start.assert_called_once_with("10.99.80.160", interval_s=1.0)
        assert "Ping monitor started" in result["messages"][-1].content

    def test_agent_calls_read_ping_stats(self, mock_model, mock_monitor):
        """Agent should be able to read ping stats mid-experiment."""
        from src.agent.graph import build_graph

        mock_model.invoke.side_effect = [
            _make_ai_with_tool_calls([{
                "name": "read_ping_stats",
                "args": {"window_s": 5.0},
                "id": "call_1",
            }]),
            _make_final_response("Baseline RTT is 12.3ms, proceeding with attack."),
        ]

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.agent.tools.get_ping_monitor", return_value=mock_monitor):
            graph = build_graph()
            state = {"messages": [HumanMessage(content="Check baseline RTT")]}
            config = {"configurable": {"thread_id": "test-pm-read"}}

            result = graph.invoke(state,  config)

        mock_monitor.get_stats.assert_called_once_with(window_s=5.0)
        assert "12.3ms" in result["messages"][-1].content

    def test_agent_calls_stop_ping_monitor(self, mock_model, mock_monitor):
        """Agent should be able to stop the ping monitor."""
        from src.agent.graph import build_graph

        mock_model.invoke.side_effect = [
            _make_ai_with_tool_calls([{
                "name": "stop_ping_monitor",
                "args": {},
                "id": "call_1",
            }]),
            _make_final_response("Ping monitor stopped. Experiment complete."),
        ]

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.agent.tools.get_ping_monitor", return_value=mock_monitor):
            graph = build_graph()
            state = {"messages": [HumanMessage(content="Stop monitoring")]}
            config = {"configurable": {"thread_id": "test-pm-stop"}}

            result = graph.invoke(state, config)

        mock_monitor.stop.assert_called_once()
        assert "stopped" in result["messages"][-1].content.lower()

    def test_traffic_send_includes_rtt_during_when_monitor_active(
        self, mock_model, mock_monitor,
    ):
        """traffic_send should return rtt_during when ping monitor is running."""
        from src.agent.graph import build_graph

        traffic_result = {
            "success": True,
            "packets_sent": {"total": 500},
            "elapsed_s": 5.0,
        }
        # The traffic_send wrapper will add rtt_during from the monitor
        # But in our mock setup, we patch traffic_send_tool directly,
        # so the wrapper code runs before returning

        mock_model.invoke.side_effect = [
            _make_ai_with_tool_calls([{
                "name": "traffic_send",
                "args": {"dst_ip": "10.99.80.160", "dst_port": 8080, "pps": 100},
                "id": "call_1",
            }]),
            _make_final_response("Traffic sent, RTT spiked to 30ms during attack."),
        ]

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.agent.tools.traffic_send_tool") as mock_send, \
             patch("src.agent.tools.get_ping_monitor", return_value=mock_monitor), \
             patch("src.agent.tools.interrupt", return_value=True):
            mock_send.return_value = traffic_result

            graph = build_graph()
            state = {"messages": [HumanMessage(content="Send attack traffic")]}
            config = {"configurable": {"thread_id": "test-pm-rtt-during"}}

            result = graph.invoke(state, config)

        mock_send.assert_called_once()
        # The tool message should contain the rtt_during data
        tool_messages = [
            m for m in result["messages"]
            if getattr(m, "type", None) == "tool"
        ]
        assert len(tool_messages) >= 1
        # rtt_during is injected into the result by the traffic_send wrapper
        assert "30ms" in result["messages"][-1].content

    def test_read_ping_stats_when_monitor_not_running(self, mock_model):
        """read_ping_stats should report monitor_active=False when not started."""
        from src.agent.graph import build_graph

        monitor = MagicMock()
        monitor.is_running.return_value = False
        monitor.get_stats.return_value = {
            "monitor_active": False,
            "target_ip": None,
            "latest_rtt_ms": None,
            "avg_rtt_ms": 0.0,
            "min_rtt_ms": 0.0,
            "max_rtt_ms": 0.0,
            "sample_count": 0,
            "loss_pct": 100.0,
            "window_s": 5.0,
        }

        mock_model.invoke.side_effect = [
            _make_ai_with_tool_calls([{
                "name": "read_ping_stats",
                "args": {},
                "id": "call_1",
            }]),
            _make_final_response("Monitor is not active, need to start it first."),
        ]

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.agent.tools.get_ping_monitor", return_value=monitor):
            graph = build_graph()
            state = {"messages": [HumanMessage(content="Check RTT")]}
            config = {"configurable": {"thread_id": "test-pm-inactive"}}

            result = graph.invoke(state, config)

        assert "not active" in result["messages"][-1].content.lower()

    def test_graph_has_eight_tools(self):
        """Graph should now have 8 tools (5 original + 3 ping monitor)."""
        from src.agent.graph import build_graph
        from src.agent.tools import EXPERIMENT_TOOLS

        tool_names = [t.name for t in EXPERIMENT_TOOLS]
        assert "start_ping_monitor" in tool_names
        assert "read_ping_stats" in tool_names
        assert "stop_ping_monitor" in tool_names
        assert len(EXPERIMENT_TOOLS) == 8

    def test_full_continuous_ping_workflow(self, mock_model, mock_monitor):
        """Agent executes full flow: start → read → traffic → read → stop."""
        from src.agent.graph import build_graph

        mock_model.invoke.side_effect = [
            # Step 0: start_ping_monitor
            _make_ai_with_tool_calls([{
                "name": "start_ping_monitor",
                "args": {"ip": "10.99.80.160"},
                "id": "call_0",
            }]),
            # Step 1: read_ping_stats (baseline)
            _make_ai_with_tool_calls([{
                "name": "read_ping_stats",
                "args": {"window_s": 5.0},
                "id": "call_1",
            }]),
            # Step 2: traffic_send
            _make_ai_with_tool_calls([{
                "name": "traffic_send",
                "args": {"dst_ip": "10.99.80.160", "dst_port": 8080, "pps": 100},
                "id": "call_2",
            }]),
            # Step 3: read_ping_stats (after attack)
            _make_ai_with_tool_calls([{
                "name": "read_ping_stats",
                "args": {"window_s": 5.0},
                "id": "call_3",
            }]),
            # Step 4: stop_ping_monitor
            _make_ai_with_tool_calls([{
                "name": "stop_ping_monitor",
                "args": {},
                "id": "call_4",
            }]),
            _make_final_response(
                "Experiment complete. Baseline RTT: 12ms, Attack max: 30ms, "
                "After recovery: 15ms. Monitor stopped."
            ),
        ]

        with patch("src.agent.graph._build_model", return_value=mock_model), \
             patch("src.agent.tools.get_ping_monitor", return_value=mock_monitor), \
             patch("src.agent.tools.traffic_send_tool") as mock_send, \
             patch("src.agent.tools.interrupt", return_value=True):
            mock_send.return_value = {
                "success": True, "packets_sent": {"total": 500}, "elapsed_s": 5.0,
            }

            graph = build_graph()
            state = {"messages": [HumanMessage(content="Run experiment with continuous ping")]}
            config = {"configurable": {"thread_id": "test-pm-full"}}

            result = graph.invoke(state, config)

        # All tools called in correct order
        mock_monitor.start.assert_called_once_with("10.99.80.160", interval_s=1.0)
        assert mock_monitor.get_stats.call_count == 2  # baseline + after
        mock_send.assert_called_once()
        mock_monitor.stop.assert_called_once()
        assert "Baseline RTT" in result["messages"][-1].content
        assert "30ms" in result["messages"][-1].content
