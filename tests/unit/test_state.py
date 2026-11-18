"""Unit tests for src/agent/state.py — unified reward / stop / best-update.

Verifies the single reward口径 (data-model 校验规则「奖励公式唯一」):
reward = avg_rtt_ms + loss_pct × 10, with inf → 0.0 semantics; the `>=`
thresholds in check_stop_condition; and the 改善归零 / 无改善 +1 semantics
of update_best. Pure functions, no I/O.
"""
import pytest

from src.agent.state import compute_reward, check_stop_condition, update_best


class TestComputeReward:
    """Unified formula: reward = avg_rtt_ms + loss_pct * 10."""

    def test_zero_loss_returns_avg(self):
        assert compute_reward(avg_rtt_ms=12.5, loss_pct=0.0) == 12.5

    def test_loss_weight_is_times_10(self):
        # loss 是正向攻击信号：20% 丢包贡献 200 分（×10 权重）
        assert compute_reward(avg_rtt_ms=5.0, loss_pct=20.0) == 205.0

    def test_inf_avg_returns_zero(self):
        # avg=inf（全部丢包、无可用 RTT 样本）→ 0.0（保留原语义）
        assert compute_reward(avg_rtt_ms=float("inf"), loss_pct=100.0) == 0.0

    def test_full_loss_with_finite_avg_counts_loss(self):
        assert compute_reward(avg_rtt_ms=30.0, loss_pct=100.0) == 1030.0


class TestCheckStopCondition:
    """达标阈值用 `>=`：等于阈值即停止（data-model 校验规则）。"""

    def test_stops_when_iteration_reaches_max(self):
        assert check_stop_condition(iteration=5, consecutive_no_improve=0,
                                    max_iters=5, no_improve_limit=3)

    def test_stops_when_counter_equals_limit(self):
        assert check_stop_condition(iteration=3, consecutive_no_improve=3,
                                    max_iters=20, no_improve_limit=3)

    def test_stops_when_counter_exceeds_limit(self):
        assert check_stop_condition(iteration=4, consecutive_no_improve=4,
                                    max_iters=20, no_improve_limit=3)

    def test_continues_under_both_limits(self):
        assert not check_stop_condition(iteration=2, consecutive_no_improve=2,
                                        max_iters=20, no_improve_limit=3)

    def test_defaults_are_20_and_5(self):
        assert check_stop_condition(iteration=20, consecutive_no_improve=0)
        assert check_stop_condition(iteration=10, consecutive_no_improve=5)
        assert not check_stop_condition(iteration=19, consecutive_no_improve=4)


class TestUpdateBest:
    """改善归零 / 无改善 +1；best_reward 为历史最优奖励。"""

    def test_improvement_updates_best_and_resets_counter(self):
        state = {"reward": 15.0, "best_reward": 10.0, "consecutive_no_improve": 4}
        update_best(state)
        assert state["best_reward"] == 15.0
        assert state["consecutive_no_improve"] == 0

    def test_no_improvement_increments_counter(self):
        state = {"reward": 8.0, "best_reward": 10.0, "consecutive_no_improve": 2}
        update_best(state)
        assert state["best_reward"] == 10.0  # unchanged
        assert state["consecutive_no_improve"] == 3

    def test_equal_reward_counts_as_no_improvement(self):
        state = {"reward": 10.0, "best_reward": 10.0, "consecutive_no_improve": 0}
        update_best(state)
        assert state["consecutive_no_improve"] == 1

    def test_defaults_when_fields_missing(self):
        state: dict = {}
        update_best(state)
        assert state["best_reward"] == 0.0
        assert state["consecutive_no_improve"] == 1  # 0.0 not > 0.0

    def test_loss_driven_improvement_counts(self):
        # 丢包上升 → 统一公式下 reward 更高 → 算改善（loss 是攻击效果）
        state = {"reward": 205.0, "best_reward": 12.0, "consecutive_no_improve": 3}
        update_best(state)
        assert state["best_reward"] == 205.0
        assert state["consecutive_no_improve"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
