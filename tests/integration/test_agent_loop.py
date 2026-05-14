"""Integration tests for agent loop state and logic."""
import operator


class TestAgentState:
    """Verify AgentState TypedDict instantiation and reducer semantics."""

    def test_initial_state_construction(self):
        """State can be created via plain dict."""
        from src.agent.state import AgentState

        state: AgentState = dict(
            iteration=0,
            traffic_params={},
            rtt_history=[],
            loss_history=[],
            best_rtt=0.0,
            consecutive_no_improve=0,
            reward=0.0,
            target_ip="10.99.80.160",
            log_path="data/experiment.jsonl",
            messages=[],
        )
        assert state["iteration"] == 0
        assert state["rtt_history"] == []
        assert state["best_rtt"] == 0.0
        assert state["target_ip"] == "10.99.80.160"

    def test_state_lookup_by_key(self):
        """Dict-style key access works."""
        from src.agent.state import AgentState

        state: AgentState = dict(
            iteration=1,
            traffic_params={},
            rtt_history=[],
            loss_history=[],
            best_rtt=0.0,
            consecutive_no_improve=0,
            reward=0.0,
            target_ip="10.99.80.160",
            log_path="data/log.jsonl",
            messages=[],
        )
        assert state["target_ip"] == "10.99.80.160"
        assert state["iteration"] == 1

    def test_rtt_history_reducer_semantics(self):
        """operator.add reducer concatenates lists."""
        existing = [1.2, 1.3]
        update = [1.5]
        result = operator.add(existing, update)
        assert result == [1.2, 1.3, 1.5]


class TestRewardComputation:
    """Verify reward = avg_rtt_ms - penalty(loss_pct)."""

    def test_reward_zero_loss(self):
        from src.agent.state import compute_reward

        reward = compute_reward(avg_rtt_ms=5.0, loss_pct=0.0)
        assert reward == 5.0

    def test_reward_with_loss(self):
        from src.agent.state import compute_reward

        reward = compute_reward(avg_rtt_ms=5.0, loss_pct=20.0)
        assert reward == 3.0  # penalty = 20 * 0.1 = 2.0

    def test_reward_all_packets_lost(self):
        from src.agent.state import compute_reward

        reward = compute_reward(avg_rtt_ms=float('inf'), loss_pct=100.0)
        assert reward == 0.0


class TestStopConditions:
    """Verify max_iters and consecutive_no_improve stopping rules."""

    def test_stops_at_max_iters(self):
        from src.agent.state import check_stop_condition

        assert check_stop_condition(iteration=20, consecutive_no_improve=0)

    def test_stops_at_no_improve_limit(self):
        from src.agent.state import check_stop_condition

        assert check_stop_condition(iteration=5, consecutive_no_improve=5)

    def test_continues_when_under_both_limits(self):
        from src.agent.state import check_stop_condition

        assert not check_stop_condition(iteration=10, consecutive_no_improve=3)


class TestBestUpdate:
    """Verify best_rtt tracking and consecutive_no_improve counter."""

    def test_new_best_resets_counter(self):
        from src.agent.state import update_best

        state = {"best_rtt": 3.0, "consecutive_no_improve": 3, "rtt_history": [5.0]}
        update_best(state)
        assert state["best_rtt"] == 5.0
        assert state["consecutive_no_improve"] == 0

    def test_no_improvement_increments_counter(self):
        from src.agent.state import update_best

        state = {"best_rtt": 5.0, "consecutive_no_improve": 2, "rtt_history": [3.0]}
        update_best(state)
        assert state["best_rtt"] == 5.0  # unchanged
        assert state["consecutive_no_improve"] == 3

    def test_empty_history_defaults(self):
        from src.agent.state import update_best

        state = {"best_rtt": 0.0, "consecutive_no_improve": 0, "rtt_history": []}
        update_best(state)
        assert state["consecutive_no_improve"] == 1  # 0.0 not > 0.0, increments
