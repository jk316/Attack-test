"""Unit tests for --instruction free-text user input in experiment mode.

No LLM, network, or file I/O — CLI args and env vars are the only inputs.
"""

import argparse
import sys
from unittest.mock import patch

import pytest

from src.agent.graph import _build_system_prompt


def _parse(argv: list[str]) -> argparse.Namespace:
    with patch.object(sys, "argv", ["main.py", *argv]):
        from src.main import parse_args
        return parse_args()


def _build_user_message(args: argparse.Namespace) -> str:
    from src.main import _build_user_message
    return _build_user_message(args)


def _experiment_args(**overrides) -> argparse.Namespace:
    base = dict(
        trex_explore=False, target_ip="10.99.80.160", pcap_path="",
        max_iters=20, no_improve_limit=5, log_path="data/x.jsonl",
        instruction="",
    )
    base.update(overrides)
    return argparse.Namespace(**base)


# ── CLI arg ────────────────────────────────────────────────────────

class TestInstructionCliArg:
    def test_default_empty(self):
        assert _parse([]).instruction == ""

    def test_parsed(self):
        args = _parse(["--instruction", "重点探索UDP洪水对RTT的影响"])
        assert args.instruction == "重点探索UDP洪水对RTT的影响"


# ── user message ───────────────────────────────────────────────────

class TestInstructionUserMessage:
    def test_message_includes_instruction(self):
        msg = _build_user_message(_experiment_args(instruction="重点探索UDP洪水"))
        assert "用户指令" in msg
        assert "重点探索UDP洪水" in msg

    def test_message_without_instruction(self):
        msg = _build_user_message(_experiment_args())
        assert "用户指令" not in msg


# ── system prompt ──────────────────────────────────────────────────

class TestInstructionSystemPrompt:
    def test_rendered_when_set(self, monkeypatch):
        monkeypatch.setenv("INSTRUCTION", "重点探索UDP洪水")
        prompt = _build_system_prompt(mode="experiment")
        assert "本次实验目标" in prompt
        assert "重点探索UDP洪水" in prompt

    def test_not_rendered_when_unset(self, monkeypatch):
        monkeypatch.delenv("INSTRUCTION", raising=False)
        prompt = _build_system_prompt(mode="experiment")
        assert "本次实验目标" not in prompt

    def test_catalog_mode_ignores_instruction(self, monkeypatch):
        monkeypatch.setenv("INSTRUCTION", "不应出现在catalog模式")
        prompt = _build_system_prompt(mode="catalog")
        assert "本次实验目标" not in prompt
