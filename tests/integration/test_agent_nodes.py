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
        with patch("random.random", return_value=0.3):  # < 0.5 so perturb
            with patch("random.uniform", return_value=0.1):  # +10%
                result = plan_params(state)

        params = result["traffic_params"]
        assert params["pps"] != state["traffic_params"]["pps"]

    def test_params_stay_within_limits(self):
        from src.agent.nodes import plan_params, MAX_PPS, MAX_DURATION_S

        state = make_state(iteration=5,
            traffic_params={"dst_port": 8080, "duration_s": MAX_DURATION_S,
                            "pps": MAX_PPS, "packet_size": 512, "flow_count": 50,
                            "iat_jitter_ms": 20})

        for _ in range(50):  # run many random iterations
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
