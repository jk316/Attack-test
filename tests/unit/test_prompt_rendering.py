"""Unit tests for system_prompt.j2 rendering via graph._build_system_prompt.

Asserts the rendered experiment-mode prompt carries the unified reward
formula (reward = avg_rtt_ms + loss_pct * 10, per data-model 校验规则
「奖励公式唯一」) and the max_iters / no_improve_limit values passed by the
caller. No LLM, network, or real file mutation — rendering is pure.
"""
import pytest

from src.agent.graph import _build_system_prompt


class TestRewardFormulaRendering:
    """统一公式文本必须出现在渲染后的实验模式提示中。"""

    def test_unified_formula_present(self):
        text = _build_system_prompt(max_iters=5, no_improve_limit=3,
                                    mode="experiment")
        assert "reward = avg_rtt_ms + loss_pct * 10" in text

    def test_no_old_penalty_formula_anywhere(self):
        # 旧口径（avg − loss × 0.1）不得残留在提示中
        text = _build_system_prompt(max_iters=5, no_improve_limit=3,
                                    mode="experiment")
        assert "avg_rtt_ms - loss_pct" not in text
        assert "loss_pct * 0.1" not in text
        assert "penalty" not in text


class TestBudgetValueRendering:
    """传入的 max_iters / no_improve_limit 必须原样出现在停止条件节。"""

    def test_max_iters_rendered(self):
        text = _build_system_prompt(max_iters=7, no_improve_limit=3,
                                    mode="experiment")
        assert "完成 7 轮时停止" in text

    def test_no_improve_limit_rendered(self):
        text = _build_system_prompt(max_iters=7, no_improve_limit=3,
                                    mode="experiment")
        assert "连续 3 轮 reward 无提升时停止" in text

    def test_distinct_budgets_produce_distinct_text(self):
        a = _build_system_prompt(max_iters=2, no_improve_limit=9,
                                 mode="experiment")
        b = _build_system_prompt(max_iters=12, no_improve_limit=4,
                                 mode="experiment")
        assert "完成 2 轮时停止" in a and "完成 2 轮时停止" not in b
        assert "连续 9 轮 reward 无提升时停止" in a
        assert "完成 12 轮时停止" in b and "连续 4 轮 reward 无提升时停止" in b


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
