"""自动批准标记测试（008-T015）。

auto-approve 路径每次放行必须输出「Auto-approved (--auto-approve)」标记
（FR-017）；input() 绝不触发；注入的 resume 决定恒为 True。
复用 tests/e2e/test_cli_loop_e2e.py 的 FakeGraph 模式（零真实 LLM/流量）。
"""

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from langchain_core.messages import AIMessage
from langgraph.types import Command

from src import main as main_mod

SUMMARY = "=== 实验总结 === 完成。"


class FakeSnapshot:
    def __init__(self, next_=(), values=None, interrupts=None):
        self.next = next_
        self.values = values or {}
        if interrupts:
            self.tasks = [SimpleNamespace(
                interrupts=[SimpleNamespace(value=interrupts)])]
        else:
            self.tasks = []


class FakeGraphOneHitl:
    """单轮 HITL 后完成。"""

    def __init__(self):
        self.resume_vals = []

    def invoke(self, state_or_command, config):
        if isinstance(state_or_command, Command):
            self.resume_vals.append(state_or_command.resume)
        return None

    def get_state(self, config):
        if not self.resume_vals:
            return FakeSnapshot(
                next_=("__interrupt__",),
                interrupts={
                    "message": "[HITL] Approve traffic send?",
                    "params": {"dst_ip": "10.99.80.160", "pps": 100},
                },
            )
        return FakeSnapshot(
            next_=(),
            values={"messages": [AIMessage(content=SUMMARY)]},
        )


@pytest.fixture
def env(monkeypatch):
    graph = FakeGraphOneHitl()
    monkeypatch.setattr(main_mod, "build_graph", lambda **kwargs: graph)
    monkeypatch.setattr(
        main_mod, "start_experiment_monitors",
        lambda target_ip, http_cfg=None: {"ping": True, "http": False},
    )
    monkeypatch.setattr(main_mod, "stop_experiment_monitors", lambda: None)
    return graph


class TestAutoApproveMarking:
    def test_auto_approve_prints_marking(self, env, capsys):
        with patch.object(sys, "argv", [
            "main.py", "--target-ip", "10.99.80.160",
            "--max-iters", "3", "--auto-approve",
        ]), patch("builtins.input") as mock_input:
            main_mod.main()

        out = capsys.readouterr().out
        # 每次自动放行输出标记（FR-017）
        assert "Auto-approved (--auto-approve)" in out
        # 自动批准注入的决定为 True
        assert env.resume_vals == [True]
        # 绝不触发人工输入
        mock_input.assert_not_called()

    def test_without_auto_approve_input_is_used(self, env, capsys):
        """无 --auto-approve 时走人工审批路径（标记不出现）。"""
        with patch.object(sys, "argv", [
            "main.py", "--target-ip", "10.99.80.160", "--max-iters", "3",
        ]), patch("builtins.input", return_value="y"):
            main_mod.main()

        out = capsys.readouterr().out
        assert "Auto-approved (--auto-approve)" not in out
        assert env.resume_vals == [True]  # 人工批准 y
