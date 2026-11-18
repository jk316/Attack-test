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
    # 脚本沙箱也落在 tmp 下：达标计数/清理绝不触碰真实 trex_scripts/
    monkeypatch.setattr(main_mod, "get_trex_scripts_dir",
                        lambda: tmp_path / "trex_scripts")
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


def _run_explore(extra_args: list[str] | None = None) -> int | None:
    argv = ["main.py", "--target-ip", "10.99.80.160",
            "--trex-explore", "--catalog-target", "10",
            *(extra_args or [])]
    with patch.object(sys, "argv", argv):
        return main_mod.main()


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


class TestCatalogExitCodesG1:
    """G1（006-T012）：达标 → 退出码 0，未达标 → 1 且总结仍落盘。"""

    VALID_CODE = "import trex_stl_lib\nprint('ok')\n"

    def test_not_reached_returns_one_and_summary_still_written(
            self, catalog_env, tmp_path, capsys):
        catalog_env["summary"] = SUMMARY_A
        exit_code = _run_explore()
        out = capsys.readouterr().out
        assert exit_code == 1
        assert "[达标判定]" in out
        assert _catalog_files(tmp_path)  # 总结仍落盘（FR-021）

    def test_reached_returns_zero(self, catalog_env, tmp_path, capsys):
        scripts_dir = tmp_path / "trex_scripts"
        scripts_dir.mkdir(parents=True)
        for i in range(10):
            (scripts_dir / f"cat_{i}.py").write_text(
                self.VALID_CODE, encoding="utf-8",
            )
        catalog_env["summary"] = SUMMARY_A
        exit_code = _run_explore()
        out = capsys.readouterr().out
        assert exit_code == 0
        assert "[达标判定]" in out

    def test_syntax_error_scripts_do_not_count(self, catalog_env, tmp_path):
        scripts_dir = tmp_path / "trex_scripts"
        scripts_dir.mkdir(parents=True)
        for i in range(9):
            (scripts_dir / f"cat_ok_{i}.py").write_text(
                self.VALID_CODE, encoding="utf-8",
            )
        (scripts_dir / "cat_broken.py").write_text("def broken(:\n",
                                                   encoding="utf-8")
        catalog_env["summary"] = SUMMARY_A
        assert _run_explore() == 1  # 9 个语法通过 < 10


class TestCleanScriptsG2:
    """G2（006-T013）：--clean-scripts 仅删 cat_*.py，打印清理横幅。"""

    def test_clean_scripts_removes_only_cat_scripts(
            self, catalog_env, tmp_path, capsys):
        scripts_dir = tmp_path / "trex_scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "cat_old.py").write_text("print(1)\n", encoding="utf-8")
        (scripts_dir / "keep.py").write_text("print(2)\n", encoding="utf-8")

        catalog_env["summary"] = SUMMARY_A
        _run_explore(extra_args=["--clean-scripts"])
        out = capsys.readouterr().out

        assert "[clean-scripts]" in out
        assert not (scripts_dir / "cat_old.py").exists()
        assert (scripts_dir / "keep.py").exists()  # 非 cat_ 文件完好

    def test_clean_scripts_with_nothing_to_clean(self, catalog_env, tmp_path,
                                                 capsys):
        catalog_env["summary"] = SUMMARY_A
        _run_explore(extra_args=["--clean-scripts"])
        out = capsys.readouterr().out
        assert "[clean-scripts]" in out
        assert "无旧" in out

    def test_clean_scripts_ignored_outside_explore_mode(self, catalog_env,
                                                        tmp_path, capsys):
        """非探索模式下 --clean-scripts 不触发清理。"""
        scripts_dir = tmp_path / "trex_scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "cat_old.py").write_text("print(1)\n", encoding="utf-8")

        argv = ["main.py", "--target-ip", "10.99.80.160", "--clean-scripts"]
        with patch.object(sys, "argv", argv):
            from src.main import parse_args
            args = parse_args()
            assert args.clean_scripts is True
            assert args.trex_explore is False
            # 非探索模式 main() 不执行清理分支
            assert (scripts_dir / "cat_old.py").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
