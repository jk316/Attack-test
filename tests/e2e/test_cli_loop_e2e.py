"""E2E test for the full CLI loop (T014 / G8 / FR-002, FR-013, FR-014 / SC-007).

Drives src/main.py's main() end-to-end with a fake graph that simulates a
mock model + tool sequence: 启动 → 预检 → 审批（两轮）→ 发送/观测 → 总结 →
清理. The fake graph emits LLM I/O through the real VerboseCallback carried in
the invoke config, so data/agent.log is written by main()'s real logging
setup. No real LLM, no real traffic, no ping subprocesses (the ping monitor is
a stub; the real one is never started).
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from langchain_core.messages import AIMessage
from langgraph.types import Command

from src import main as main_mod

SUMMARY = "=== 实验总结 ===\n最佳 RTT: 85.3ms，最佳 loss: 2.1%，实验完成。"
AGENT_LOG = Path(main_mod._agent_log_path())


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


class FakeMonitor:
    """Ping monitor stub: running until stop() is called (SC-007 contract)."""

    def __init__(self):
        self.running = True
        self.stopped = False

    def is_running(self) -> bool:
        return self.running

    def stop(self) -> None:
        self.running = False
        self.stopped = True


class FakeGraph:
    """Simulates a mock-model/tool sequence over the real polling loop.

    Round 1: interrupt on traffic_send (HITL) → resume.
    Round 2: interrupt on mixed_traffic_send (HITL) → resume.
    After that: completes with the final summary message.
    Each invoke emits [LLM INPUT]/[LLM OUTPUT] through the real callback so
    the real FileHandler writes data/agent.log.
    """

    def __init__(self, total_hitl_rounds: int = 2):
        self.total_hitl_rounds = total_hitl_rounds
        self.resume_vals: list[bool] = []
        self.invokes = []

    @staticmethod
    def _emit(cfg, content: str, tool_calls):
        callbacks = cfg.get("callbacks") or []
        cb = callbacks[0] if callbacks else None
        if cb is None:
            return
        msg = SimpleNamespace(
            type="ai", content=content, tool_calls=tool_calls,
            additional_kwargs={"reasoning_content": "内部推理"},
        )
        cb.on_chat_model_start(None, [[msg]])
        cb.on_chat_model_end(SimpleNamespace(
            generations=[[SimpleNamespace(message=msg)]]
        ))

    def invoke(self, state_or_command, config):
        self.invokes.append(state_or_command)
        if isinstance(state_or_command, Command):
            self.resume_vals.append(state_or_command.resume)
            self._emit(config, "已批准，执行并观测 RTT…", [])
        else:
            self._emit(config, "提议流量参数",
                       [{"name": "traffic_send", "args": {}}])
        return None

    def get_state(self, config):
        if len(self.resume_vals) < self.total_hitl_rounds:
            n = len(self.resume_vals) + 1
            return FakeSnapshot(
                next_=("__interrupt__",),
                interrupts={
                    "message": f"[HITL] Approve traffic send? (round {n})",
                    "params": {"dst_ip": "10.99.80.160", "pps": 100 * n},
                },
            )
        return FakeSnapshot(
            next_=(),
            values={"messages": [AIMessage(content=SUMMARY)]},
        )


@pytest.fixture
def env(monkeypatch, tmp_path):
    graph = FakeGraph()
    monitor = FakeMonitor()
    monkeypatch.setattr(main_mod, "build_graph", lambda **kwargs: graph)
    monkeypatch.setattr(
        main_mod, "start_experiment_monitors",
        lambda target_ip, http_cfg=None: {"ping": True, "http": False},
    )
    # 单客户端 main() 的 finally 调用 stop_experiment_monitors() 清理监控；
    # 这里让它驱动 FakeMonitor.stop() 以保持 SC-007 断言语义。
    monkeypatch.setattr(main_mod, "stop_experiment_monitors",
                        lambda: monitor.stop())
    # 隔离 agent.log：使用真实 data/agent.log（gitignored），先清空
    AGENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    if AGENT_LOG.exists():
        AGENT_LOG.unlink()
    return SimpleNamespace(graph=graph, monitor=monitor)


class TestFullCliLoop:
    def test_complete_loop_approve_summarize_cleanup(self, env, capsys):
        with patch.object(sys, "argv", [
            "main.py", "--target-ip", "10.99.80.160", "--max-iters", "3",
        ]), patch("builtins.input", lambda prompt: "y"):
            main_mod.main()

        out = capsys.readouterr().out
        # 启动
        assert "=== Closed-Loop Experiment ===" in out
        # 两轮审批弹窗 + 参数明细
        assert "[HITL] Approve traffic send? (round 1)" in out
        assert "[HITL] Approve traffic send? (round 2)" in out
        assert '"pps": 100' in out and '"pps": 200' in out
        # 批准后继续
        assert env.graph.resume_vals == [True, True]
        # 总结输出
        assert "=== Experiment Complete ===" in out
        assert SUMMARY in out
        # 无残留 ping 监控（mock 语义：running→stop）
        assert env.monitor.stopped is True
        assert env.monitor.running is False

    def test_agent_log_has_llm_io_records(self, env):
        with patch.object(sys, "argv", [
            "main.py", "--target-ip", "10.99.80.160", "--max-iters", "3",
        ]), patch("builtins.input", lambda prompt: "y"):
            main_mod.main()

        assert AGENT_LOG.exists()
        text = AGENT_LOG.read_text(encoding="utf-8")
        assert "[LLM INPUT]" in text
        assert "[LLM OUTPUT]" in text
        assert "traffic_send" in text

    def test_eof_reject_still_completes_with_cleanup(self, env, capsys):
        with patch.object(sys, "argv", [
            "main.py", "--target-ip", "10.99.80.160", "--max-iters", "3",
        ]), patch("builtins.input", side_effect=EOFError):
            main_mod.main()

        out = capsys.readouterr().out
        assert "No input — rejecting by default" in out
        assert env.graph.resume_vals == [False, False]
        assert env.monitor.stopped is True  # 拒绝路径也清理监控

    def test_preflight_rejects_non_allowlist_target(self, env, capsys):
        with patch.object(sys, "argv", [
            "main.py", "--target-ip", "192.168.1.99", "--max-iters", "3",
        ]):
            with pytest.raises(SystemExit) as exc:
                main_mod.main()
        assert exc.value.code != 0
        assert "不在 allowlist" in capsys.readouterr().err
        assert env.graph.invokes == []  # 未构建/未发起任何图调用


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
