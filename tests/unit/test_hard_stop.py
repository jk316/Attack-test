"""Deterministic hard-verdict unit tests (T015 / G1 / D1 / D5 / SC-003).

Drives src/agent/state.py's verdict functions with deterministic observation
sequences: constant-no-improvement must force-stop exactly at the
no_improve_limit-th round, constant-improvement must not stop early, a
constant-continue run stops at max_iters, and rounds whose observation does
not cover the attack window (covers_attack_window=false) must not count
towards the no-improve counter (D5). Also asserts the two verdict fields'
semantics: best_reward (历史最优奖励) and consecutive_no_improve
(改善归零 / 无改善 +1). Pure functions — no I/O.
"""
import pytest

from src.agent.state import (
    apply_observation,
    check_stop_condition,
    compute_reward,
)


def _obs(avg, loss=0.0, covers=True):
    return {"avg_rtt_ms": avg, "loss_pct": loss, "covers_attack_window": covers}


def _round(state, iteration, obs, max_iters=100, limit=4):
    state = apply_observation(state, obs)
    stop = check_stop_condition(
        iteration=iteration,
        consecutive_no_improve=state["consecutive_no_improve"],
        max_iters=max_iters,
        no_improve_limit=limit,
    )
    return state, stop


class TestConstantNoImprovement:
    """恒无改善序列：第 no_improve_limit 轮强制停止（SC-003 前半）。"""

    def test_stops_exactly_at_no_improve_limit(self):
        limit = 4
        state = {"best_reward": 100.0, "consecutive_no_improve": 0}
        for iteration in range(1, limit + 2):
            state, stop = _round(state, iteration, _obs(10.0, 0.0), limit=limit)
            if iteration < limit:
                assert not stop, f"第 {iteration} 轮不应停止"
            else:
                assert stop, f"第 {iteration} 轮必须强制停止"
        assert state["consecutive_no_improve"] == limit + 1

    def test_best_reward_kept_on_no_improvement(self):
        state = {"best_reward": 100.0, "consecutive_no_improve": 0}
        for _ in range(3):
            state, _ = _round(state, 1, _obs(10.0, 0.0))
        assert state["best_reward"] == 100.0  # 无改善不更新历史最优
        assert state["consecutive_no_improve"] == 3


class TestConstantImprovement:
    """恒改善序列：不提前停止；best_reward 单调上升（SC-003 反例）。"""

    def test_never_stops_early(self):
        state = {"best_reward": 0.0, "consecutive_no_improve": 0}
        for iteration, avg in enumerate([10.0, 20.0, 30.0, 40.0], start=1):
            state, stop = _round(state, iteration, _obs(avg, 0.0),
                                 max_iters=10, limit=4)
            assert not stop
            assert state["consecutive_no_improve"] == 0

    def test_best_reward_tracks_max(self):
        state = {"best_reward": 0.0, "consecutive_no_improve": 0}
        for avg in [10.0, 20.0, 30.0, 40.0]:
            state, _ = _round(state, 1, _obs(avg, 0.0))
        assert state["best_reward"] == 40.0


class TestMaxItersUnconditionalStop:
    """恒继续序列：到达 max_iters 无条件停止（SC-003 后半）。"""

    def test_stops_at_max_iters_even_while_improving(self):
        state = {"best_reward": 0.0, "consecutive_no_improve": 0}
        stop = False
        for iteration in range(1, 7):
            state, stop = _round(state, iteration, _obs(float(iteration * 10)),
                                 max_iters=6, limit=99)
        assert stop  # 第 6 轮：iteration == max_iters → 无条件停止

    def test_does_not_stop_before_max_iters(self):
        state = {"best_reward": 0.0, "consecutive_no_improve": 0}
        for iteration in range(1, 6):
            state, stop = _round(state, iteration, _obs(float(iteration * 10)),
                                 max_iters=6, limit=99)
            assert not stop


class TestUnreliableObservationSkipped:
    """covers_attack_window=false 的轮次不计入无改善计数（D5）。"""

    def test_uncovered_round_does_not_increment_counter(self):
        state = {"best_reward": 100.0, "consecutive_no_improve": 2}
        state, stop = _round(state, 3, _obs(10.0, 0.0, covers=False))
        assert not stop
        assert state["consecutive_no_improve"] == 2  # 不变
        assert state["best_reward"] == 100.0
        assert state["last_round_counted"] is False

    def test_uncovered_round_with_huge_avg_is_not_improvement(self):
        state = {"best_reward": 100.0, "consecutive_no_improve": 0}
        state, _ = _round(state, 1, _obs(9999.0, 0.0, covers=False))
        assert state["best_reward"] == 100.0  # 不采信
        assert state["consecutive_no_improve"] == 0

    def test_missing_observation_is_skipped(self):
        state = {"best_reward": 100.0, "consecutive_no_improve": 1}
        state, _ = _round(state, 2, None)
        assert state["consecutive_no_improve"] == 1
        assert state["last_round_counted"] is False

    def test_covered_round_after_skipped_counts_again(self):
        state = {"best_reward": 100.0, "consecutive_no_improve": 2}
        state, _ = _round(state, 3, _obs(10.0, 0.0, covers=False))
        state, _ = _round(state, 4, _obs(10.0, 0.0, covers=True))
        assert state["consecutive_no_improve"] == 3  # 恢复计数
        assert state["last_round_counted"] is True


class TestVerdictFieldSemantics:
    """best_reward 与 consecutive_no_improve 两字段的更新语义。"""

    def test_improvement_resets_counter(self):
        state = {"best_reward": 10.0, "consecutive_no_improve": 5}
        state, _ = _round(state, 6, _obs(20.0, 0.0))
        assert state["best_reward"] == 20.0
        assert state["consecutive_no_improve"] == 0

    def test_no_improvement_increments_counter(self):
        state = {"best_reward": 10.0, "consecutive_no_improve": 5}
        state, _ = _round(state, 6, _obs(5.0, 0.0))
        assert state["best_reward"] == 10.0
        assert state["consecutive_no_improve"] == 6

    def test_loss_improvement_counts_via_unified_formula(self):
        # loss 上升 → reward = avg + loss×10 更高 → 算改善（统一公式）
        assert compute_reward(5.0, 20.0) == 205.0
        state = {"best_reward": 10.0, "consecutive_no_improve": 3}
        state, _ = _round(state, 4, _obs(5.0, 20.0))
        assert state["best_reward"] == 205.0
        assert state["consecutive_no_improve"] == 0

    def test_inf_avg_becomes_zero_reward(self):
        # avg=inf → 0.0（T004 保留语义）→ 无改善
        state = {"best_reward": 10.0, "consecutive_no_improve": 0}
        state, _ = _round(state, 1, _obs(float("inf"), 100.0))
        assert state["best_reward"] == 10.0
        assert state["consecutive_no_improve"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
