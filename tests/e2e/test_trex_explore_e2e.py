"""E2E test for --trex-explore catalog mode (T021 / G6 / FR-001, FR-011 / SC-006).

Runs src/main.py's main() through the REAL build_graph with a fake model that
immediately returns a final summary. Asserts: zero interrupts / zero approval
prompts (input() is never called), the available tool set contains only the
2 catalog tools (captured via bind_tools), the summary lands in
output/trex_attack_catalog_<时间戳>.md, and two consecutive runs do not
overwrite each other. No real LLM, network, or traffic.
"""
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from langchain_core.messages import AIMessage

from src import main as main_mod
from src.agent import graph as graph_mod

SUMMARY_A = ("# TRex 攻击目录（mock 运行 A）\n"
             "| 攻击名称 | 攻击类别 | 脚本文件 |\n"
             "| UDP 洪水 | 流量放大 | cat_udp_flood.py |")
SUMMARY_B = ("# TRex 攻击目录（mock 运行 B）\n"
             "| 攻击名称 | 攻击类别 | 脚本文件 |\n"
             "| DNS 放大 | 反射放大 | cat_dns_amplify.py |")

CATALOG_PATTERN = re.compile(r"^trex_attack_catalog_\d{8}_\d{6}(_\d{6})?\.md$")


class CapturingModel:
    """Fake ChatOpenAI: captures bound tools, returns the given final message."""

    model_name = "deepseek-chat"

    def __init__(self, response: AIMessage):
        self._response = response
        self.bound_tools = None

    def bind_tools(self, tools, **kwargs):
        self.bound_tools = list(tools)
        return self

    def invoke(self, messages, config=None, **kwargs):
        return self._response


@pytest.fixture
def catalog_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # output/ 落在 tmp 下，不污染仓库
    captured = {}

    def fake_build_graph(**kwargs):
        model = CapturingModel(AIMessage(content=captured["summary"]))
        monkeypatch.setattr(graph_mod, "_build_model", lambda: model)
        captured["model"] = model
        real = graph_mod.build_graph(**kwargs)
        return real

    monkeypatch.setattr(main_mod, "build_graph", fake_build_graph)
    monkeypatch.setattr(main_mod, "get_ping_monitor",
                        lambda: _FakeMonitor())
    monkeypatch.setattr("builtins.input",
                        lambda prompt: (_ for _ in ()).throw(
                            AssertionError("目录模式不得出现审批输入")))
    return captured


class _FakeMonitor:
    def is_running(self):
        return False

    def stop(self):
        pass


def _run_explore():
    with patch.object(sys, "argv", ["main.py", "--target-ip", "10.99.80.160",
                                    "--trex-explore", "--catalog-target", "10"]):
        main_mod.main()


def _catalog_files(cwd: Path) -> list[Path]:
    out = cwd / "output"
    if not out.exists():
        return []
    return sorted(out.glob("trex_attack_catalog_*.md"))


class TestCatalogE2E:
    def test_zero_approval_and_tool_restriction(self, catalog_env, capsys):
        catalog_env["summary"] = SUMMARY_A
        _run_explore()
        out = capsys.readouterr().out
        # 零审批：无 HITL 弹窗、无自动批准行
        assert "[HITL]" not in out
        assert "Approve?" not in out
        # 可用工具集仅目录生成工具（真实 build_graph 的绑定结果）
        names = sorted(t.name for t in catalog_env["model"].bound_tools)
        assert names == ["run_python_file", "write_python_file"]

    def test_summary_written_with_timestamp_name(self, catalog_env, tmp_path,
                                                 capsys):
        catalog_env["summary"] = SUMMARY_A
        _run_explore()
        out = capsys.readouterr().out
        assert "Attack catalog saved to:" in out
        files = _catalog_files(tmp_path)
        assert len(files) == 1
        assert CATALOG_PATTERN.match(files[0].name)
        assert files[0].read_text(encoding="utf-8") == SUMMARY_A

    def test_two_consecutive_runs_do_not_overwrite(self, catalog_env,
                                                   tmp_path, capsys):
        catalog_env["summary"] = SUMMARY_A
        _run_explore()
        catalog_env["summary"] = SUMMARY_B
        _run_explore()
        files = _catalog_files(tmp_path)
        assert len(files) == 2  # 互不覆盖（SC-006）
        names = {f.name for f in files}
        assert len(names) == 2  # 文件名各不相同（时间戳唯一）
        contents = {f.read_text(encoding="utf-8") for f in files}
        assert contents == {SUMMARY_A, SUMMARY_B}

    def test_empty_final_message_writes_no_summary(self, catalog_env,
                                                   tmp_path, capsys):
        # 边界情况：最终消息为空 → 不写摘要文件，正常结束并提示
        catalog_env["summary"] = ""
        _run_explore()
        out = capsys.readouterr().out
        assert _catalog_files(tmp_path) == []
        assert "最终消息为空" in out
        assert "=== Experiment Complete ===" in out  # 正常结束


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
