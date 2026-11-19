"""Integration tests for budget enforcement in the main loop (T019 / SC-003/005).

Drives src/main.py's main() with a fake graph whose tool results carry
measured rtt_during / observation_window payloads. The real polling loop +
runtime hard verdict (G1/D1/D5) then decides when to force-stop. Verifies
`--no-improve-limit 2 --max-iters 6` actually takes effect and the stop
timing is exact: constant-no-improvement stops at the 3rd round (counter
hits 2), constant-improvement runs to max_iters, and a round whose
observation does not cover the attack window is skipped (D5). No LLM, no
network, no traffic.
"""
import json
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from src import main as main_mod


def _tool_result(round_no, avg, loss=0.0, covers=True):
    payload = {
        "success": True,
        "packets_sent": {"total": 100},
        "rtt_during": {
            "avg_rtt_ms": avg,
            "loss_pct": loss,
            "samples": [],
        },
        "observation_window": {
            "covers_attack_window": covers,
            "note": "观测窗口已覆盖攻击窗口",
        },
        "round": round_no,
    }
    return ToolMessage(content=json.dumps(payload), tool_call_id=f"c{round_no}")


class FakeSnapshot:
    def __init__(self, next_=(), values=None, interrupts=None):
        self.next = next_
        self.values = values or {}
        if interrupts:
            self.tasks = [SimpleNamespace(
                interrupts=[SimpleNamespace(value=interrupts)]
            )]
        else:
            self.tasks = []


class FakeGraph:
    """Interrupts once per round; each completed round appends a tool result.

    observation_fn(round_no) → (avg, loss, covers) provides the measured
    observation for that round. `available_rounds` bounds how many interrupts
    the graph will offer (simulating the model proposing that many rounds).
    """

    def __init__(self, observation_fn, available_rounds=8):
        self.observation_fn = observation_fn
        self.available_rounds = available_rounds
        self.resume_vals: list[bool] = []
        self.invokes = []

    def invoke(self, state_or_command, config):
        self.invokes.append(state_or_command)
        if isinstance(state_or_command, Command):
            self.resume_vals.append(state_or_command.resume)
        return None

    def _messages(self):
        n = len(self.resume_vals)
        msgs = []
        for r in range(1, n + 1):
            msgs.append(AIMessage(content=f"第 {r} 轮决策"))
            avg, loss, covers = self.observation_fn(r)
            msgs.append(_tool_result(r, avg, loss, covers))
        msgs.append(AIMessage(content=f"第 {n + 1} 轮决策"))
        return msgs

    def get_state(self, config):
        n = len(self.resume_vals)
        msgs = self._messages()
        if n < self.available_rounds:
            return FakeSnapshot(
                next_=("__interrupt__",),
                interrupts={
                    "message": f"[HITL] Approve traffic send? (round {n + 1})",
                    "params": {"dst_ip": "10.99.80.160", "pps": 100},
                },
                values={"messages": msgs},
            )
        return FakeSnapshot(next_=(), values={"messages": msgs})


@pytest.fixture
def run_main(monkeypatch):
    def _run(graph, argv_extra=None):
        monkeypatch.setattr(main_mod, "build_graph", lambda **kwargs: graph)
        monkeypatch.setattr(main_mod, "get_ping_monitor",
                            lambda: SimpleNamespace(is_running=lambda: False))
        argv = ["main.py", "--target-ip", "10.99.80.160",
                "--max-iters", "6", "--no-improve-limit", "2",
                "--auto-approve"] + (argv_extra or [])
        with patch.object(sys, "argv", argv):
            main_mod.main()
    return _run


class TestConstantNoImprovement:
    def test_stops_after_third_round_not_max_iters(self, run_main, capsys):
        # 恒无改善：每轮 avg=10, loss=0（第 1 轮相对 best=0 是改善）
        graph = FakeGraph(lambda r: (10.0, 0.0, True))
        run_main(graph)
        out = capsys.readouterr().out
        # 第 1 轮改善（best 0→10），第 2、3 轮连续无改善 → 第 3 轮强制停止
        assert graph.resume_vals == [True, True, True]
        assert len(graph.resume_vals) == 3  # 未跑到 max_iters=6
        assert "[硬裁决]" in out
        assert "连续 2 轮无改善" in out
        assert "强制停止" in out

    def test_stop_timing_exact(self, run_main, capsys):
        graph = FakeGraph(lambda r: (10.0, 0.0, True))
        run_main(graph)
        out = capsys.readouterr().out
        assert "共执行 3 轮" in out  # SC-003：精确等于 no_improve_limit+1


class TestConstantImprovement:
    def test_runs_to_max_iters(self, run_main, capsys):
        # 恒改善：avg 逐轮上升 → 计数保持 0 → 直到 max_iters=6 停止
        graph = FakeGraph(lambda r: (float(r * 10), 0.0, True))
        run_main(graph)
        out = capsys.readouterr().out
        assert graph.resume_vals == [True] * 6
        assert "[硬裁决]" in out
        assert "达到最大轮数 6" in out
        assert "共执行 6 轮" in out


class TestUnreliableRoundSkipped:
    def test_uncovered_round_does_not_count(self, run_main, capsys):
        # 第 2 轮观测未覆盖攻击窗口 → 不计入（D5）→ 停止推迟到第 4 轮
        def obs(r):
            if r == 2:
                return (999.0, 0.0, False)  # 诱人的大 RTT 但观测不可靠
            return (10.0, 0.0, True)
        graph = FakeGraph(obs)
        run_main(graph)
        out = capsys.readouterr().out
        assert graph.resume_vals == [True, True, True, True]
        assert len(graph.resume_vals) == 4
        assert "连续 2 轮无改善" in out
        assert "共执行 4 轮" in out


class NoInterruptGraph:
    """Completes immediately with a final summary (catalog-mode shape)."""

    def invoke(self, state_or_command, config):
        return None

    def get_state(self, config):
        return FakeSnapshot(
            next_=(),
            values={"messages": [AIMessage(content="攻击目录摘要（mock）")]},
        )


class TestCatalogModeExempt:
    def test_catalog_mode_never_runs_verdict(self, monkeypatch, capsys, tmp_path):
        # 目录模式（D6）：无 RTT 观测语义，硬裁决不生效、零审批
        monkeypatch.chdir(tmp_path)  # catalog 摘要写到 tmp 下的 output/
        graph = NoInterruptGraph()
        monkeypatch.setattr(main_mod, "build_graph", lambda **kwargs: graph)
        monkeypatch.setattr(main_mod, "get_ping_monitor",
                            lambda: SimpleNamespace(is_running=lambda: False))
        with patch.object(sys, "argv", [
            "main.py", "--target-ip", "10.99.80.160", "--trex-explore",
        ]):
            main_mod.main()
        out = capsys.readouterr().out
        assert "[硬裁决]" not in out
        assert "[HITL]" not in out  # 目录模式零审批
        assert "Attack catalog saved to:" in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
