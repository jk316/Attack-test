"""Tests for LangGraph StateGraph builder."""
from unittest.mock import patch
import pytest
from langgraph.graph.state import CompiledStateGraph


def make_state(**overrides):
    state = {
        "iteration": 0,
        "traffic_params": {
            "dst_port": 8080, "duration_s": 5, "pps": 50,
            "packet_size": 64, "flow_count": 1, "iat_jitter_ms": 5,
        },
        "rtt_history": [],
        "loss_history": [],
        "best_rtt": 0.0,
        "consecutive_no_improve": 0,
        "reward": 0.0,
        "target_ip": "10.99.80.160",
        "log_path": "data/test.jsonl",
        "messages": [],
    }
    state.update(overrides)
    return state


class TestBuildGraph:
    """Verify graph structure and compilation."""

    def test_build_graph_returns_compiled_graph(self):
        from src.agent.graph import build_graph
        graph = build_graph()
        assert isinstance(graph, CompiledStateGraph)

    def test_all_five_nodes_registered(self):
        from src.agent.graph import build_graph
        graph = build_graph()

        # The builder has a 'nodes' attribute (public) or we verify via a test run
        builder = graph.builder
        assert hasattr(builder, "nodes")
        node_names = list(builder.nodes.keys())
        expected = {"plan_params", "send_traffic", "measure_rtt", "log_result", "update_state"}
        assert expected.issubset(set(node_names))

    def test_graph_has_checkpointer(self):
        from src.agent.graph import build_graph
        graph = build_graph()
        assert graph.checkpointer is not None


class TestGraphTopology:
    """Verify the graph structure via inspection and mock-based runs."""

    def test_should_continue_stop_at_max_iters(self):
        from src.agent.graph import should_continue
        from langgraph.graph import END

        state = make_state(iteration=20, consecutive_no_improve=0)
        assert should_continue(state) == END

    def test_should_continue_stop_at_no_improve(self):
        from src.agent.graph import should_continue
        from langgraph.graph import END

        state = make_state(iteration=5, consecutive_no_improve=5)
        assert should_continue(state) == END

    def test_should_continue_loop(self):
        from src.agent.graph import should_continue

        state = make_state(iteration=10, consecutive_no_improve=3)
        assert should_continue(state) == "plan_params"

    def test_graph_invoke_runs_to_completion(self):
        """A full run with mocked tools completes without error."""
        from src.agent.graph import build_graph

        graph = build_graph()
        initial = make_state(iteration=19)  # near max_iters, one pass finishes

        # Mock all side-effect tools
        with patch("src.agent.nodes.ping_rtt_tool") as mock_ping, \
             patch("src.agent.nodes.traffic_send_tool") as mock_send, \
             patch("src.agent.nodes.log_tool") as mock_log, \
             patch("src.agent.nodes.interrupt", return_value=True):

            mock_ping.return_value = {"success": True, "avg_rtt_ms": 5.0, "loss_pct": 0.0}

            config = {"configurable": {"thread_id": "test-001"}}
            result = graph.invoke(initial, config)

        assert result["iteration"] == 20  # incremented once
        assert len(result["rtt_history"]) == 1
        assert result["rtt_history"][-1] == 5.0

    def test_graph_invoke_loop_multiple_iterations(self):
        """A multi-iteration run loops correctly."""
        from src.agent.graph import build_graph

        graph = build_graph()
        initial = make_state(iteration=17)  # room for 3 iterations

        with patch("src.agent.nodes.ping_rtt_tool") as mock_ping, \
             patch("src.agent.nodes.traffic_send_tool") as mock_send, \
             patch("src.agent.nodes.log_tool") as mock_log, \
             patch("src.agent.nodes.interrupt", return_value=True):

            # Decreasing RTT: should trigger 5 no-improve counts
            mock_ping.return_value = {"success": True, "avg_rtt_ms": 5.0, "loss_pct": 0.0}

            config = {"configurable": {"thread_id": "test-002"}}
            result = graph.invoke(initial, config)

        # Ran iterations 17, 18, 19 → 20 is at max_iters
        assert result["iteration"] == 20
        assert len(result["rtt_history"]) == 3
