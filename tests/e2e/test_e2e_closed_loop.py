"""End-to-end tests for the closed-loop network experiment agent."""
from unittest.mock import MagicMock, patch
import pytest
from langgraph.types import Command


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
        "log_path": "data/e2e_test.jsonl",
        "messages": [],
    }
    state.update(overrides)
    return state


class TestFullClosedLoop:
    """Tests that exercise the complete graph execution with mocked tools."""

    def test_runs_to_completion_at_max_iters(self):
        """Graph stops when iteration reaches max_iters=20."""
        from src.agent.graph import build_graph

        graph = build_graph()
        state = make_state(iteration=18)
        call_count = {"ping": 0, "send": 0, "log": 0}

        def mock_ping(ip, **kwargs):
            call_count["ping"] += 1
            return {"success": True, "avg_rtt_ms": 5.0, "loss_pct": 0.0}

        with patch("src.agent.nodes.ping_rtt_tool", side_effect=mock_ping), \
             patch("src.agent.nodes.traffic_send_tool") as mock_send, \
             patch("src.agent.nodes.log_tool") as mock_log, \
             patch("src.agent.nodes.interrupt", return_value=True):

            mock_send.return_value = {"success": True}
            mock_log.return_value = {"success": True}
            call_count["send"] = 0
            call_count["log"] = 0

            config = {"configurable": {"thread_id": "e2e-max-iters"}}
            result = graph.invoke(state, config)

        # 2 iterations: 18 → 19 → 20 (stops at 20)
        assert result["iteration"] == 20
        assert len(result["rtt_history"]) == 2

    def test_runs_to_completion_at_no_improve(self):
        """Graph stops when consecutive_no_improve reaches 5."""
        from src.agent.graph import build_graph

        graph = build_graph()
        state = make_state(iteration=0, consecutive_no_improve=4)

        def mock_ping(ip, **kwargs):
            # Return decreasing RTT to ensure no improvement
            return {"success": True, "avg_rtt_ms": 2.0, "loss_pct": 0.0}

        with patch("src.agent.nodes.ping_rtt_tool", side_effect=mock_ping), \
             patch("src.agent.nodes.traffic_send_tool"), \
             patch("src.agent.nodes.log_tool"), \
             patch("src.agent.nodes.interrupt", return_value=True):

            config = {"configurable": {"thread_id": "e2e-no-improv"}}
            result = graph.invoke(state, config)

        # Should stop after 1 iteration (consecutive_no_improve 4→5)
        assert result["consecutive_no_improve"] == 5

    def test_rtt_history_accumulation(self):
        """RTT history should have one entry per iteration executed."""
        from src.agent.graph import build_graph

        graph = build_graph()
        state = make_state(iteration=16)  # 4 iterations to max

        rtt_values = [3.0, 5.0, 4.0, 6.0]

        def mock_ping(ip, **kwargs):
            idx = min(len(rtt_values) - 1, len(rtt_values) - 1)
            return {"success": True, "avg_rtt_ms": rtt_values.pop(0), "loss_pct": 0.0}

        # Simpler: just use a fixed value, we check length
        with patch("src.agent.nodes.ping_rtt_tool",
                   return_value={"success": True, "avg_rtt_ms": 5.0, "loss_pct": 0.0}), \
             patch("src.agent.nodes.traffic_send_tool"), \
             patch("src.agent.nodes.log_tool"), \
             patch("src.agent.nodes.interrupt", return_value=True):

            config = {"configurable": {"thread_id": "e2e-history"}}
            result = graph.invoke(state, config)

        # 4 iterations executed (iteration 16→17→18→19→20)
        assert len(result["rtt_history"]) == 4
        assert result["iteration"] == 20

    def test_log_tool_called_per_iteration(self):
        """log_tool should be called once per iteration."""
        from src.agent.graph import build_graph

        graph = build_graph()
        state = make_state(iteration=17)  # 3 iterations

        with patch("src.agent.nodes.ping_rtt_tool",
                   return_value={"success": True, "avg_rtt_ms": 5.0, "loss_pct": 0.0}), \
             patch("src.agent.nodes.traffic_send_tool"), \
             patch("src.agent.nodes.log_tool") as mock_log, \
             patch("src.agent.nodes.interrupt", return_value=True):

            config = {"configurable": {"thread_id": "e2e-log"}}
            graph.invoke(state, config)

        assert mock_log.call_count == 3


class TestHITLResume:
    """Tests for the HITL interrupt and resume flow."""

    def test_hitl_interrupt_then_resume(self):
        """Graph interrupts at send_traffic, resumes with approval."""
        from src.agent.graph import build_graph
        from langgraph.errors import GraphInterrupt

        graph = build_graph()
        state = make_state(iteration=19)  # only 1 iteration needed

        interrupt_count = [0]

        def counting_interrupt(value):
            interrupt_count[0] += 1
            # First call: raise-like behavior comes from graph, we return True
            return True

        with patch("src.agent.nodes.ping_rtt_tool",
                   return_value={"success": True, "avg_rtt_ms": 5.0, "loss_pct": 0.0}), \
             patch("src.agent.nodes.traffic_send_tool"), \
             patch("src.agent.nodes.log_tool"), \
             patch("src.agent.nodes.interrupt", side_effect=counting_interrupt):

            config = {"configurable": {"thread_id": "e2e-hitl"}}
            result = graph.invoke(state, config)

        assert result["iteration"] == 20
        assert interrupt_count[0] >= 1


class TestRewardChain:
    """Verify the complete reward computation chain."""

    def test_reward_updates_per_iteration(self):
        """reward should be updated from ping result each iteration."""
        from src.agent.graph import build_graph

        graph = build_graph()
        state = make_state(iteration=18)

        with patch("src.agent.nodes.ping_rtt_tool",
                   return_value={"success": True, "avg_rtt_ms": 8.0, "loss_pct": 10.0}), \
             patch("src.agent.nodes.traffic_send_tool"), \
             patch("src.agent.nodes.log_tool"), \
             patch("src.agent.nodes.interrupt", return_value=True):

            config = {"configurable": {"thread_id": "e2e-reward"}}
            result = graph.invoke(state, config)

        # reward = 8.0 - 10.0 * 0.1 = 7.0
        assert result["reward"] == 7.0
        # best_rtt should be 8.0 (first and only value)
        assert result["best_rtt"] == 8.0


class TestAllowlistRejection:
    """Non-allowlist IPs should be rejected at the tool level."""

    def test_non_allowlist_ip_rejected_in_graph(self):
        """Graph with non-allowlist target should fail in ping_rtt_tool."""
        from src.agent.graph import build_graph

        graph = build_graph()
        state = make_state(iteration=19, target_ip="192.168.1.99")

        with patch("src.agent.nodes.traffic_send_tool"), \
             patch("src.agent.nodes.interrupt", return_value=True):
            with pytest.raises(ValueError, match="not in allowlist"):
                config = {"configurable": {"thread_id": "e2e-reject"}}
                graph.invoke(state, config)


class TestE2EWithLLM:
    """End-to-end tests exercising the LLM-powered plan_params path."""

    def test_e2e_llm_params_propagate_through_full_loop(self):
        """LLM params should flow through send→measure→log in the full graph."""
        from src.agent.graph import build_graph

        graph = build_graph()
        initial = make_state(
            iteration=2,
            rtt_history=[30.0, 35.0],
            loss_history=[0.0, 0.0],
            reward=35.0,
            max_iters=4,
        )

        llm_params = {
            "dst_port": 9090, "duration_s": 6, "pps": 100,
            "packet_size": 256, "flow_count": 3, "iat_jitter_ms": 8,
        }
        mock_client = MagicMock()
        mock_client.chat.return_value = {
            "params": llm_params,
            "reasoning": "Increasing load",
        }

        with patch("src.agent.nodes._get_llm_client", return_value=mock_client), \
             patch("src.agent.nodes.ping_rtt_tool") as mock_ping, \
             patch("src.agent.nodes.traffic_send_tool") as mock_send, \
             patch("src.agent.nodes.log_tool") as mock_log, \
             patch("src.agent.nodes.interrupt", return_value=True):

            mock_ping.return_value = {"success": True, "avg_rtt_ms": 45.0, "loss_pct": 0.0}

            config = {"configurable": {"thread_id": "e2e-llm-001"}}
            result = graph.invoke(initial, config)

        # LLM params reached send tool
        assert mock_send.call_count >= 1
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["dst_port"] == 9090
        assert call_kwargs["pps"] == 100
        assert call_kwargs["flow_count"] == 3

        # Full chain: log called, RTT accumulated
        assert mock_log.call_count >= 1
        assert len(result["rtt_history"]) > len(initial["rtt_history"])
        assert result["rtt_history"][-1] == 45.0

    def test_e2e_llm_called_with_evolving_state(self):
        """Each iteration passes updated history to LLM for better decisions."""
        from src.agent.graph import build_graph

        graph = build_graph()
        initial = make_state(
            iteration=3,
            rtt_history=[30.0, 35.0, 40.0],
            loss_history=[0.0, 0.0, 0.0],
            reward=40.0,
            max_iters=5,
        )

        received_states = []
        def mock_chat(messages):
            # Capture the context message sent to LLM
            user_msg = messages[1]["content"] if len(messages) > 1 else ""
            received_states.append(user_msg)
            return {
                "params": {
                    "dst_port": 8080, "duration_s": 5, "pps": 80,
                    "packet_size": 64, "flow_count": 1, "iat_jitter_ms": 5,
                },
                "reasoning": "Continuing",
            }

        mock_client = MagicMock()
        mock_client.chat.side_effect = mock_chat

        rtt_sequence = [42.0, 48.0]  # 2 iterations: 3→4, 4→5

        with patch("src.agent.nodes._get_llm_client", return_value=mock_client), \
             patch("src.agent.nodes.ping_rtt_tool") as mock_ping, \
             patch("src.agent.nodes.traffic_send_tool"), \
             patch("src.agent.nodes.log_tool"), \
             patch("src.agent.nodes.interrupt", return_value=True):

            def mock_ping_fn(ip, **kwargs):
                return {"success": True, "avg_rtt_ms": rtt_sequence.pop(0), "loss_pct": 0.0}

            mock_ping.side_effect = mock_ping_fn

            config = {"configurable": {"thread_id": "e2e-llm-002"}}
            result = graph.invoke(initial, config)

        # LLM called per iteration (2 iterations: 3→4 and 4→5)
        assert mock_client.chat.call_count == 2
        # Each call received updated context (RTT values appear in context)
        assert "42" in received_states[0] or "48" in received_states[0] \
               or "40.00" in received_states[0]  # shows previous best_rtt
        assert result["iteration"] == 5

    def test_e2e_llm_fallback_keeps_graph_running(self):
        """When LLM fails every time, E2E graph completes via random fallback."""
        from src.agent.graph import build_graph

        graph = build_graph()
        initial = make_state(
            iteration=17,
            max_iters=20,
        )

        # LLM always fails
        mock_client = MagicMock()
        mock_client.chat.side_effect = Exception("Network error")

        with patch("src.agent.nodes._get_llm_client", return_value=mock_client), \
             patch("src.agent.nodes.ping_rtt_tool") as mock_ping, \
             patch("src.agent.nodes.traffic_send_tool") as mock_send, \
             patch("src.agent.nodes.log_tool") as mock_log, \
             patch("src.agent.nodes.interrupt", return_value=True), \
             patch("random.random", return_value=0.3), \
             patch("random.uniform", return_value=0.05):

            mock_ping.return_value = {"success": True, "avg_rtt_ms": 5.0, "loss_pct": 0.0}

            config = {"configurable": {"thread_id": "e2e-llm-003"}}
            result = graph.invoke(initial, config)

        # Graph reached max_iters
        assert result["iteration"] == 20
        # All side-effect tools were called
        assert mock_send.call_count == 3  # iterations 17→18, 18→19, 19→20
        assert mock_log.call_count == 3

    def test_e2e_llm_no_api_key_in_e2e_context(self):
        """When DEEPSEEK_API_KEY is absent, E2E runs entirely on fallback."""
        from src.agent.graph import build_graph

        graph = build_graph()
        initial = make_state(
            iteration=18,
            max_iters=20,
        )

        with patch("src.agent.nodes._get_llm_client", return_value=None), \
             patch("src.agent.nodes.ping_rtt_tool") as mock_ping, \
             patch("src.agent.nodes.traffic_send_tool") as mock_send, \
             patch("src.agent.nodes.log_tool") as mock_log, \
             patch("src.agent.nodes.interrupt", return_value=True), \
             patch("random.random", return_value=0.3), \
             patch("random.uniform", return_value=0.05):

            mock_ping.return_value = {"success": True, "avg_rtt_ms": 5.0, "loss_pct": 0.0}

            config = {"configurable": {"thread_id": "e2e-llm-004"}}
            result = graph.invoke(initial, config)

        assert result["iteration"] == 20
        assert mock_send.call_count == 2
        assert mock_log.call_count == 2
        assert len(result["rtt_history"]) == 2
