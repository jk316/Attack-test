"""Tests for LangGraph StateGraph builder."""
from unittest.mock import MagicMock, patch
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

    def test_all_six_nodes_registered(self):
        from src.agent.graph import build_graph
        graph = build_graph()

        builder = graph.builder
        assert hasattr(builder, "nodes")
        node_names = list(builder.nodes.keys())
        expected = {"pcap_profile", "plan_params", "send_traffic", "measure_rtt", "log_result", "update_state"}
        assert expected.issubset(set(node_names))

    def test_graph_has_checkpointer(self):
        from src.agent.graph import build_graph
        graph = build_graph()
        assert graph.checkpointer is not None


class TestPcapInGraph:
    """Verify pcap_profile node is wired correctly in the graph."""

    def test_pcap_profile_runs_before_plan_params(self):
        """When pcap_path is set and iteration=0, pcap_profile stores analysis."""
        from src.agent.graph import build_graph

        graph = build_graph()
        initial = make_state(iteration=0, pcap_path="fake.pcap",
            traffic_params={}, max_iters=1)

        mock_profile = {"top_dst_ports": [9090], "iat_ms_stats": {"p50": 3.0}}

        with patch("src.agent.nodes.pcap_profile_tool", return_value=mock_profile), \
             patch("src.agent.nodes.ping_rtt_tool") as mock_ping, \
             patch("src.agent.nodes.traffic_send_tool") as mock_send, \
             patch("src.agent.nodes.log_tool"), \
             patch("src.agent.nodes.interrupt", return_value=True):

            mock_ping.return_value = {"success": True, "avg_rtt_ms": 30.0, "loss_pct": 0.0}

            config = {"configurable": {"thread_id": "pcap-graph-001"}}
            result = graph.invoke(initial, config)

        # pcap_profile was stored in state
        assert result.get("pcap_profile") == mock_profile
        # plan_params used pcap data (port 9090 from pcap, not default 8080)
        assert mock_send.call_count == 1
        send_params = mock_send.call_args.kwargs
        assert send_params["dst_port"] == 9090
        assert result["iteration"] == 1


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
        initial = make_state(iteration=19)

        with patch("src.agent.nodes.ping_rtt_tool") as mock_ping, \
             patch("src.agent.nodes.traffic_send_tool") as mock_send, \
             patch("src.agent.nodes.log_tool") as mock_log, \
             patch("src.agent.nodes.interrupt", return_value=True):

            mock_ping.return_value = {"success": True, "avg_rtt_ms": 5.0, "loss_pct": 0.0}

            config = {"configurable": {"thread_id": "test-001"}}
            result = graph.invoke(initial, config)

        assert result["iteration"] == 20
        assert len(result["rtt_history"]) == 1
        assert result["rtt_history"][-1] == 5.0

    def test_graph_invoke_loop_multiple_iterations(self):
        """A multi-iteration run loops correctly."""
        from src.agent.graph import build_graph

        graph = build_graph()
        initial = make_state(iteration=17)

        with patch("src.agent.nodes.ping_rtt_tool") as mock_ping, \
             patch("src.agent.nodes.traffic_send_tool") as mock_send, \
             patch("src.agent.nodes.log_tool") as mock_log, \
             patch("src.agent.nodes.interrupt", return_value=True):

            mock_ping.return_value = {"success": True, "avg_rtt_ms": 5.0, "loss_pct": 0.0}

            config = {"configurable": {"thread_id": "test-002"}}
            result = graph.invoke(initial, config)

        assert result["iteration"] == 20
        assert len(result["rtt_history"]) == 3


class TestGraphWithLLM:
    """Graph-level tests that exercise the LLM-powered plan_params path."""

    def test_graph_invoke_llm_params_propagate_to_send(self):
        """LLM-suggested params should reach traffic_send_tool via graph."""
        from src.agent.graph import build_graph

        graph = build_graph()
        initial = make_state(iteration=2,
            rtt_history=[30.0, 35.0],
            loss_history=[0.0, 0.0],
            reward=35.0,
            max_iters=3,
        )

        llm_params = {
            "dst_port": 9090, "duration_s": 7, "pps": 120,
            "packet_size": 256, "flow_count": 3, "iat_jitter_ms": 10,
        }
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "params": llm_params,
            "reasoning": "Test",
        }

        with patch("src.agent.nodes._get_llm_client", return_value=mock_client), \
             patch("src.agent.nodes.ping_rtt_tool") as mock_ping, \
             patch("src.agent.nodes.traffic_send_tool") as mock_send, \
             patch("src.agent.nodes.log_tool"), \
             patch("src.agent.nodes.interrupt", return_value=True):

            mock_ping.return_value = {"success": True, "avg_rtt_ms": 40.0, "loss_pct": 0.0}

            config = {"configurable": {"thread_id": "llm-graph-001"}}
            result = graph.invoke(initial, config)

        # Verify LLM params reached traffic_send_tool
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["dst_port"] == 9090
        assert call_kwargs["duration_s"] == 7
        assert call_kwargs["pps"] == 120
        assert call_kwargs["packet_size"] == 256
        assert call_kwargs["flow_count"] == 3
        assert call_kwargs["iat_jitter_ms"] == 10

        # Verify graph still completed correctly
        assert result["iteration"] > initial["iteration"]
        assert len(result["rtt_history"]) > 0

    def test_graph_invoke_llm_plans_across_multiple_iterations(self):
        """LLM should be called for each iteration (2+), each with updated state."""
        from src.agent.graph import build_graph

        graph = build_graph()
        initial = make_state(iteration=3,
            rtt_history=[30.0, 35.0, 40.0],
            loss_history=[0.0, 0.0, 0.0],
            reward=40.0,
            max_iters=5,
        )

        call_count = [0]

        def mock_chat(messages):
            call_count[0] += 1
            # Increase pps each call to verify different params per iteration
            return {
                "params": {
                    "dst_port": 8080, "duration_s": 5,
                    "pps": 50 + call_count[0] * 10,
                    "packet_size": 64, "flow_count": 1, "iat_jitter_ms": 5,
                },
                "reasoning": f"Call {call_count[0]}",
            }

        mock_client = MagicMock()
        mock_client.chat.side_effect = mock_chat

        with patch("src.agent.nodes._get_llm_client", return_value=mock_client), \
             patch("src.agent.nodes.ping_rtt_tool") as mock_ping, \
             patch("src.agent.nodes.traffic_send_tool") as mock_send, \
             patch("src.agent.nodes.log_tool"), \
             patch("src.agent.nodes.interrupt", return_value=True):

            mock_ping.return_value = {"success": True, "avg_rtt_ms": 45.0, "loss_pct": 0.0}

            config = {"configurable": {"thread_id": "llm-graph-002"}}
            result = graph.invoke(initial, config)

        # 2 iterations run (iteration 3→4→5), LLM called per iteration >= 1
        assert call_count[0] >= 2
        # traffic_send_tool should have been called with different params
        all_pps = [c.kwargs["pps"] for c in mock_send.call_args_list]
        assert len(set(all_pps)) >= 2  # different pps per call

    def test_graph_invoke_llm_fallback_during_graph_run(self):
        """When LLM fails mid-graph, fallback keeps the graph running."""
        from src.agent.graph import build_graph

        graph = build_graph()
        initial = make_state(iteration=4,
            rtt_history=[30.0, 35.0, 40.0, 42.0],
            loss_history=[0.0, 0.0, 0.0, 0.0],
            reward=42.0,
            max_iters=6,
        )

        # LLM fails on every call
        mock_client = MagicMock()
        mock_client.chat.side_effect = Exception("Simulated API failure")

        with patch("src.agent.nodes._get_llm_client", return_value=mock_client), \
             patch("src.agent.nodes.ping_rtt_tool") as mock_ping, \
             patch("src.agent.nodes.traffic_send_tool") as mock_send, \
             patch("src.agent.nodes.log_tool"), \
             patch("src.agent.nodes.interrupt", return_value=True), \
             patch("random.random", return_value=0.3), \
             patch("random.uniform", return_value=0.05):

            mock_ping.return_value = {"success": True, "avg_rtt_ms": 50.0, "loss_pct": 0.0}

            config = {"configurable": {"thread_id": "llm-graph-003"}}
            result = graph.invoke(initial, config)

        # Graph should complete despite LLM failures
        assert result["iteration"] == 6  # reached max_iters
        assert len(result["rtt_history"]) == 6  # 4 initial + 2 iterations run
        # traffic_send_tool was called (fallback worked)
        assert mock_send.call_count == 2

    def test_graph_invoke_llm_no_api_key_graceful(self):
        """When _get_llm_client returns None, graph completes via fallback."""
        from src.agent.graph import build_graph

        graph = build_graph()
        initial = make_state(iteration=18,
            max_iters=20,
        )

        with patch("src.agent.nodes._get_llm_client", return_value=None), \
             patch("src.agent.nodes.ping_rtt_tool") as mock_ping, \
             patch("src.agent.nodes.traffic_send_tool") as mock_send, \
             patch("src.agent.nodes.log_tool"), \
             patch("src.agent.nodes.interrupt", return_value=True), \
             patch("random.random", return_value=0.3), \
             patch("random.uniform", return_value=0.05):

            mock_ping.return_value = {"success": True, "avg_rtt_ms": 5.0, "loss_pct": 0.0}

            config = {"configurable": {"thread_id": "llm-graph-004"}}
            result = graph.invoke(initial, config)

        assert result["iteration"] == 20
        assert mock_send.call_count == 2
        assert len(result["rtt_history"]) == 2
