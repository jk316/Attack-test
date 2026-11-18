"""Integration tests for the CLI HITL polling loop (G5 / FR-004/005 / SC-004).

Drives src/main.py's main() with a fake graph: the first invoke returns a
pending interrupt (message + params payload); the resume Command captured by
the fake graph proves the polling loop's approval decision (approve / reject
/ auto-approve / EOF default-reject). Rejection produces "HITL rejected" and
0 packets; approval continues the run. No real LLM, no network, no traffic —
build_graph is monkeypatched.
"""
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from langchain_core.messages import AIMessage
from langgraph.types import Command

from src import main as main_mod

HITL_MESSAGE = "[HITL] Approve traffic send?"
HITL_PARAMS = {"dst_ip": "10.99.80.160", "pps": 100, "duration_s": 5}


class FakeSnapshot:
    def __init__(self, next_=(), values=None, interrupts=None):
        self.next = next_
        self.values = values or {}
        if interrupts:
            task = SimpleNamespace(
                interrupts=[SimpleNamespace(value=interrupts)]
            )
            self.tasks = [task]
        else:
            self.tasks = []


class FakeGraph:
    """Graph stub that interrupts once, then completes based on the resume value."""

    REJECT_CONTENT = "HITL rejected by operator：本轮 0 报文发送，未产生任何流量。"
    APPROVE_CONTENT = "已批准：流量发送完成，本轮观测 avg_rtt_ms=85.3。"

    def __init__(self):
        self.invokes = []
        self.resume_vals = []

    def invoke(self, state_or_command, config):
        self.invokes.append(state_or_command)
        if isinstance(state_or_command, Command):
            self.resume_vals.append(state_or_command.resume)
        return None

    def get_state(self, config):
        if len(self.invokes) == 1:
            # After the initial invoke: one HITL interrupt pending.
            return FakeSnapshot(
                next_=("__interrupt__",),
                interrupts={"message": HITL_MESSAGE, "params": HITL_PARAMS},
            )
        approved = self.resume_vals[-1]
        content = self.APPROVE_CONTENT if approved else self.REJECT_CONTENT
        return FakeSnapshot(next_=(), values={"messages": [AIMessage(content=content)]})


@pytest.fixture
def fake_graph(monkeypatch):
    graph = FakeGraph()
    monkeypatch.setattr(main_mod, "build_graph", lambda **kwargs: graph)
    return graph


def _run_main(argv, input_func):
    with patch.object(sys, "argv", ["main.py", *argv]), \
            patch("builtins.input", input_func):
        main_mod.main()


class TestPayloadDisplay:
    def test_interrupt_payload_shows_message_and_params(self, fake_graph, capsys):
        _run_main(["--target-ip", "10.99.80.160", "--max-iters", "3"],
                  lambda prompt: "y")
        out = capsys.readouterr().out
        assert HITL_MESSAGE in out
        assert '"dst_ip": "10.99.80.160"' in out
        assert '"pps": 100' in out


class TestReject:
    def test_reject_reports_hitl_rejected_and_zero_packets(self, fake_graph, capsys):
        _run_main(["--target-ip", "10.99.80.160", "--max-iters", "3"],
                  lambda prompt: "n")
        assert fake_graph.resume_vals == [False]
        out = capsys.readouterr().out
        assert "HITL rejected" in out
        assert "0 报文" in out

    def test_reject_passes_resume_false_to_graph(self, fake_graph):
        _run_main(["--target-ip", "10.99.80.160", "--max-iters", "3"],
                  lambda prompt: "n")
        assert isinstance(fake_graph.invokes[0], dict)  # initial state
        assert fake_graph.resume_vals == [False]


class TestApprove:
    def test_approve_continues_run(self, fake_graph, capsys):
        _run_main(["--target-ip", "10.99.80.160", "--max-iters", "3"],
                  lambda prompt: "y")
        assert fake_graph.resume_vals == [True]
        out = capsys.readouterr().out
        assert "已批准" in out
        assert "avg_rtt_ms=85.3" in out


class TestAutoApprove:
    def test_auto_approve_skips_prompt(self, fake_graph):
        def fail_if_called(prompt):
            raise AssertionError("input() must not be called with --auto-approve")

        _run_main(["--target-ip", "10.99.80.160", "--max-iters", "3",
                   "--auto-approve"],
                  fail_if_called)
        assert fake_graph.resume_vals == [True]


class TestEofDefaultReject:
    def test_eof_defaults_to_reject(self, fake_graph, capsys):
        def raise_eof(prompt):
            raise EOFError

        _run_main(["--target-ip", "10.99.80.160", "--max-iters", "3"],
                  raise_eof)
        assert fake_graph.resume_vals == [False]
        out = capsys.readouterr().out
        assert "No input — rejecting by default" in out
        assert "HITL rejected" in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
