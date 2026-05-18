"""Tests for LangGraph node functions - RED stage."""
from unittest.mock import patch, MagicMock
import pytest


def make_state(**overrides):
    """Build a minimal valid AgentState dict for testing."""
    state = {
        "iteration": 0,
        "traffic_params": {
            "dst_port": 8080,
            "duration_s": 5,
            "pps": 50,
            "packet_size": 64,
            "flow_count": 1,
            "iat_jitter_ms": 5,
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


# ── pcap_profile ──────────────────────────────────────────────────

class TestPcapProfile:
    def test_analyzes_pcap_on_iteration_0(self):
        """pcap_profile should call pcap_profile_tool and store results."""
        from src.agent.nodes import pcap_profile

        state = make_state(iteration=0, pcap_path="test.pcap")
        mock_result = {
            "top_dst_ips": ["10.0.0.1"],
            "top_dst_ports": [8080],
            "packet_size_hist": {"64": 100, "128": 50},
            "iat_ms_stats": {"mean": 10.5, "p50": 8.0, "p90": 15.0},
            "flow_stats": {"approx_flow_count": 10, "timeout_s": 30},
            "payload_len_stats": {"mean": 64.0},
            "notes": "test profile",
        }

        with patch("src.agent.nodes.pcap_profile_tool", return_value=mock_result):
            result = pcap_profile(state)

        assert result["pcap_profile"] == mock_result

    def test_skips_on_iteration_gt_0(self):
        """pcap_profile should return empty dict when iteration > 0."""
        from src.agent.nodes import pcap_profile

        state = make_state(iteration=3, pcap_path="test.pcap")
        result = pcap_profile(state)
        assert result == {}

    def test_skips_when_pcap_path_empty(self):
        """pcap_profile should return empty dict when pcap_path is not set."""
        from src.agent.nodes import pcap_profile

        state = make_state(iteration=0)  # no pcap_path
        result = pcap_profile(state)
        assert result == {}

    def test_skips_when_pcap_path_blank(self):
        """pcap_profile should return empty dict when pcap_path is ''."""
        from src.agent.nodes import pcap_profile

        state = make_state(iteration=0, pcap_path="")
        result = pcap_profile(state)
        assert result == {}


class TestPcapInitialParams:
    def test_derives_params_from_pcap_profile(self):
        """_pcap_initial_params should map PCAP analysis to traffic params."""
        from src.agent.nodes import _pcap_initial_params, MAX_IAT_JITTER_MS, MAX_FLOW_COUNT

        pcap = {
            "top_dst_ports": [9090],
            "packet_size_hist": {"128": 80, "64": 20},
            "iat_ms_stats": {"mean": 7.0, "p50": 6.0, "p90": 12.0},
            "flow_stats": {"approx_flow_count": 8, "timeout_s": 30},
        }
        params = _pcap_initial_params(pcap)

        assert params["dst_port"] == 9090
        assert params["packet_size"] == 128  # peak of histogram
        assert params["iat_jitter_ms"] == 6  # p50 clamped to MAX_IAT_JITTER_MS
        assert params["flow_count"] == 4      # approx_flows // 2 = 4

    def test_falls_back_to_defaults_on_empty_profile(self):
        """Empty pcap_profile should yield DEFAULT_PARAMS."""
        from src.agent.nodes import _pcap_initial_params, DEFAULT_PARAMS

        params = _pcap_initial_params({})
        assert params == DEFAULT_PARAMS

    def test_clamps_jitter_to_max(self):
        """IAT p50 > MAX_IAT_JITTER_MS should be clamped."""
        from src.agent.nodes import _pcap_initial_params, MAX_IAT_JITTER_MS

        pcap = {"iat_ms_stats": {"p50": 999}}
        params = _pcap_initial_params(pcap)
        assert params["iat_jitter_ms"] == MAX_IAT_JITTER_MS

    def test_clamps_flow_count_to_max(self):
        """approx_flow_count // 2 > MAX_FLOW_COUNT should be clamped."""
        from src.agent.nodes import _pcap_initial_params, MAX_FLOW_COUNT

        pcap = {"flow_stats": {"approx_flow_count": 200}}
        params = _pcap_initial_params(pcap)
        assert params["flow_count"] == MAX_FLOW_COUNT

    def test_clamps_packet_size_to_max(self):
        """Packet size > MAX_PACKET_SIZE should be ignored, falling back."""
        from src.agent.nodes import _pcap_initial_params, MAX_PACKET_SIZE, DEFAULT_PARAMS

        pcap = {"packet_size_hist": {"9999": 100}}
        params = _pcap_initial_params(pcap)
        assert params["packet_size"] == DEFAULT_PARAMS["packet_size"]

    def test_skips_port_when_top_ports_empty(self):
        """Empty top_dst_ports should keep default port."""
        from src.agent.nodes import _pcap_initial_params, DEFAULT_PARAMS

        pcap = {"top_dst_ports": []}
        params = _pcap_initial_params(pcap)
        assert params["dst_port"] == DEFAULT_PARAMS["dst_port"]


class TestPlanParamsWithPcap:
    def test_iter_0_uses_pcap_data(self):
        """plan_params iteration 0 should use pcap_profile for initial params."""
        from src.agent.nodes import plan_params

        pcap = {
            "top_dst_ports": [3000],
            "packet_size_hist": {"256": 50},
            "iat_ms_stats": {"p50": 3.0},
            "flow_stats": {"approx_flow_count": 4},
        }
        state = make_state(iteration=0, traffic_params={}, pcap_profile=pcap)
        result = plan_params(state)

        assert result["traffic_params"]["dst_port"] == 3000
        assert result["traffic_params"]["packet_size"] == 256
        assert result["traffic_params"]["iat_jitter_ms"] == 3
        assert result["traffic_params"]["flow_count"] == 2  # 4 // 2

    def test_iter_0_falls_back_without_pcap(self):
        """plan_params iteration 0 without pcap_profile should use defaults."""
        from src.agent.nodes import plan_params, DEFAULT_PARAMS

        state = make_state(iteration=0, traffic_params={})
        result = plan_params(state)
        assert result["traffic_params"] == DEFAULT_PARAMS


# ── plan_params ───────────────────────────────────────────────────

class TestPlanParams:
    def test_first_iteration_returns_defaults(self):
        from src.agent.nodes import plan_params, DEFAULT_PARAMS

        state = make_state(iteration=0, traffic_params={})
        result = plan_params(state)
        assert result["traffic_params"] == DEFAULT_PARAMS

    def test_subsequent_iteration_perturbs_params(self):
        from src.agent.nodes import plan_params

        state = make_state(iteration=3)
        with patch("random.random", return_value=0.3):
            with patch("random.uniform", return_value=0.1):
                result = plan_params(state)

        params = result["traffic_params"]
        assert params["pps"] != state["traffic_params"]["pps"]

    def test_params_stay_within_limits(self):
        from src.agent.nodes import plan_params, MAX_PPS, MAX_DURATION_S

        state = make_state(iteration=5,
            traffic_params={"dst_port": 8080, "duration_s": MAX_DURATION_S,
                            "pps": MAX_PPS, "packet_size": 512, "flow_count": 50,
                            "iat_jitter_ms": 20})

        for _ in range(50):
            result = plan_params(state)
            p = result["traffic_params"]
            assert 1 <= p["pps"] <= MAX_PPS
            assert 1 <= p["duration_s"] <= MAX_DURATION_S
            assert 1 <= p["flow_count"] <= 50
            assert 0 <= p["iat_jitter_ms"] <= 20

    def test_preserves_keys(self):
        from src.agent.nodes import plan_params

        state = make_state(iteration=2)
        result = plan_params(state)
        assert set(result["traffic_params"].keys()) == set(state["traffic_params"].keys())

    # ── LLM integration tests ──────────────────────────────────────

    def test_llm_success_returns_params(self):
        """plan_params should return LLM-suggested params on success."""
        from src.agent.nodes import plan_params

        state = make_state(iteration=2,
            rtt_history=[30.0, 40.0],
            loss_history=[0.0, 5.0],
            reward=39.5,
        )
        llm_response = {
            "params": {
                "dst_port": 9090, "duration_s": 6, "pps": 100,
                "packet_size": 256, "flow_count": 3, "iat_jitter_ms": 10,
            },
            "reasoning": "Increasing load to push RTT higher",
        }
        mock_client = MagicMock()
        mock_client.chat.return_value = llm_response

        with patch("src.agent.nodes._get_llm_client", return_value=mock_client):
            result = plan_params(state)

        assert result["traffic_params"]["pps"] == 100
        assert result["traffic_params"]["packet_size"] == 256
        assert result["traffic_params"]["flow_count"] == 3

    def test_llm_failure_falls_back_to_random(self):
        """plan_params should fall back to random perturbation on LLM error."""
        from src.agent.nodes import plan_params

        state = make_state(iteration=3)
        orig_pps = state["traffic_params"]["pps"]

        mock_client = MagicMock()
        mock_client.chat.side_effect = Exception("API error")

        with patch("src.agent.nodes._get_llm_client", return_value=mock_client), \
             patch("random.random", return_value=0.3), \
             patch("random.uniform", return_value=0.1):
            result = plan_params(state)

        # Should have been perturbed by random fallback (different from original)
        assert result["traffic_params"]["pps"] != orig_pps

    def test_llm_params_clamped_to_limits(self):
        """LLM-returned params outside bounds should be clamped."""
        from src.agent.nodes import plan_params, MAX_PPS, MAX_DURATION_S, MAX_IAT_JITTER_MS

        state = make_state(iteration=2,
            rtt_history=[30.0],
            loss_history=[0.0],
            reward=30.0,
        )
        llm_response = {
            "params": {
                "dst_port": 99999,  # > 65535
                "duration_s": 999,  # > MAX_DURATION_S
                "pps": -5,          # < 1
                "packet_size": 9999, # > MAX_PACKET_SIZE
                "flow_count": 0,    # < 1
                "iat_jitter_ms": 999, # > MAX_IAT_JITTER_MS
            },
        }
        mock_client = MagicMock()
        mock_client.chat.return_value = llm_response

        with patch("src.agent.nodes._get_llm_client", return_value=mock_client):
            result = plan_params(state)

        p = result["traffic_params"]
        assert p["dst_port"] == 65535
        assert p["duration_s"] == MAX_DURATION_S
        assert p["pps"] == 1
        assert p["packet_size"] == 512
        assert p["flow_count"] == 1
        assert p["iat_jitter_ms"] == MAX_IAT_JITTER_MS

    def test_llm_missing_keys_filled_from_previous(self):
        """Missing keys in LLM response should be filled from prev params."""
        from src.agent.nodes import plan_params

        state = make_state(iteration=2,
            rtt_history=[30.0],
            loss_history=[0.0],
            reward=30.0,
        )
        # LLM only returns partial params
        llm_response = {
            "params": {
                "pps": 120,
                "flow_count": 5,
            },
        }
        mock_client = MagicMock()
        mock_client.chat.return_value = llm_response

        with patch("src.agent.nodes._get_llm_client", return_value=mock_client):
            result = plan_params(state)

        p = result["traffic_params"]
        # LLM-provided
        assert p["pps"] == 120
        assert p["flow_count"] == 5
        # Filled from previous
        assert p["dst_port"] == state["traffic_params"]["dst_port"]
        assert p["duration_s"] == state["traffic_params"]["duration_s"]
        assert p["packet_size"] == state["traffic_params"]["packet_size"]
        assert p["iat_jitter_ms"] == state["traffic_params"]["iat_jitter_ms"]

    def test_llm_non_integer_values_converted(self):
        """Float or string param values should be converted to int."""
        from src.agent.nodes import plan_params

        state = make_state(iteration=2,
            rtt_history=[30.0],
            loss_history=[0.0],
            reward=30.0,
        )
        llm_response = {
            "params": {
                "dst_port": 8080.7,
                "duration_s": "6",
                "pps": 100.2,
                "packet_size": "256",
                "flow_count": 3.9,
                "iat_jitter_ms": 5,
            },
        }
        mock_client = MagicMock()
        mock_client.chat.return_value = llm_response

        with patch("src.agent.nodes._get_llm_client", return_value=mock_client):
            result = plan_params(state)

        p = result["traffic_params"]
        assert isinstance(p["dst_port"], int)
        assert p["dst_port"] == 8080  # int(8080.7) = 8080
        assert isinstance(p["duration_s"], int)
        assert p["duration_s"] == 6    # int("6") = 6
        assert isinstance(p["pps"], int)
        assert p["pps"] == 100         # int(100.2) = 100
        assert isinstance(p["packet_size"], int)
        assert p["packet_size"] == 256 # int("256") = 256
        assert isinstance(p["flow_count"], int)
        assert p["flow_count"] == 3    # int(3.9) = 3

    def test_llm_non_integer_unconvertible_falls_back(self):
        """Unconvertible string param values should fall back to previous."""
        from src.agent.nodes import plan_params

        state = make_state(iteration=2,
            rtt_history=[30.0],
            loss_history=[0.0],
            reward=30.0,
        )
        llm_response = {
            "params": {
                "pps": "high",  # cannot convert to int
                "flow_count": 5,
            },
        }
        mock_client = MagicMock()
        mock_client.chat.return_value = llm_response

        with patch("src.agent.nodes._get_llm_client", return_value=mock_client):
            result = plan_params(state)

        p = result["traffic_params"]
        # "high" is unconvertible → fall back to previous
        assert p["pps"] == state["traffic_params"]["pps"]
        assert p["flow_count"] == 5

    def test_llm_client_unavailable_falls_back(self):
        """When _get_llm_client returns None, fall back to random."""
        from src.agent.nodes import plan_params

        state = make_state(iteration=2)
        orig_pps = state["traffic_params"]["pps"]

        with patch("src.agent.nodes._get_llm_client", return_value=None), \
             patch("random.random", return_value=0.3), \
             patch("random.uniform", return_value=0.1):
            result = plan_params(state)

        assert result["traffic_params"]["pps"] != orig_pps

    def test_llm_response_missing_params_key_falls_back(self):
        """When LLM response has no 'params' key, fall back to random."""
        from src.agent.nodes import plan_params

        state = make_state(iteration=2,
            rtt_history=[30.0],
            loss_history=[0.0],
        )
        mock_client = MagicMock()
        mock_client.chat.return_value = {"reasoning": "I forgot the params key"}

        with patch("src.agent.nodes._get_llm_client", return_value=mock_client), \
             patch("random.random", return_value=0.3), \
             patch("random.uniform", return_value=0.1):
            result = plan_params(state)

        # Should have fallen back to random (params differ)
        assert result["traffic_params"]["pps"] != state["traffic_params"]["pps"]


# ── send_traffic ───────────────────────────────────────────────────

class TestSendTraffic:
    def test_calls_traffic_send_tool_with_correct_params(self):
        from src.agent.nodes import send_traffic

        state = make_state(iteration=2)
        with patch("src.agent.nodes.interrupt", return_value=True), \
             patch("src.agent.nodes.traffic_send_tool") as mock_send:
            send_traffic(state)

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["dst_ip"] == "10.99.80.160"
        assert call_kwargs["dst_port"] == 8080
        assert call_kwargs["pps"] == 50

    def test_hitl_rejected_returns_error(self):
        from src.agent.nodes import send_traffic

        state = make_state()
        with patch("src.agent.nodes.interrupt", return_value=False):
            result = send_traffic(state)

        assert result == {"error": "HITL rejected"}


# ── measure_rtt ────────────────────────────────────────────────────

class TestMeasureRtt:
    def test_computes_reward_and_appends_history(self):
        from src.agent.nodes import measure_rtt

        state = make_state()
        mock_ping = {"success": True, "avg_rtt_ms": 5.0, "loss_pct": 10.0}

        with patch("src.agent.nodes.ping_rtt_tool", return_value=mock_ping):
            result = measure_rtt(state)

        assert result["rtt_history"] == [5.0]
        assert result["loss_history"] == [10.0]
        assert result["reward"] == 4.0  # 5.0 - 10.0 * 0.1

    def test_inf_rtt_returns_zero_reward(self):
        from src.agent.nodes import measure_rtt

        state = make_state()
        mock_ping = {"success": True, "avg_rtt_ms": float("inf"), "loss_pct": 100.0}

        with patch("src.agent.nodes.ping_rtt_tool", return_value=mock_ping):
            result = measure_rtt(state)

        assert result["reward"] == 0.0


# ── log_result ─────────────────────────────────────────────────────

class TestLogResult:
    def test_calls_log_tool_with_correct_entry(self):
        from src.agent.nodes import log_result

        state = make_state(iteration=3, rtt_history=[1.2, 1.5], loss_history=[0.0, 10.0])

        with patch("src.agent.nodes.log_tool") as mock_log:
            log_result(state)

        mock_log.assert_called_once()
        entry = mock_log.call_args[0][1]
        assert entry["iteration"] == 3
        assert entry["rtt"] == 1.5
        assert entry["loss"] == 10.0
        assert entry["params"] == state["traffic_params"]


# ── update_state ───────────────────────────────────────────────────

class TestUpdateState:
    def test_increments_iteration(self):
        from src.agent.nodes import update_state

        state = make_state(iteration=3, rtt_history=[5.0])
        result = update_state(state)
        assert result["iteration"] == 4

    def test_new_best_updates_and_resets_counter(self):
        from src.agent.nodes import update_state

        state = make_state(best_rtt=3.0, consecutive_no_improve=4, rtt_history=[5.0])
        result = update_state(state)
        assert result["best_rtt"] == 5.0
        assert result["consecutive_no_improve"] == 0

    def test_no_improvement_increments_counter(self):
        from src.agent.nodes import update_state

        state = make_state(best_rtt=5.0, consecutive_no_improve=2, rtt_history=[3.0])
        result = update_state(state)
        assert result["best_rtt"] == 5.0
        assert result["consecutive_no_improve"] == 3
