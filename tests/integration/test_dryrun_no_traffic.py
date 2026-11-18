"""dry-run / explore 零流量零审批回归测试（008-T016）。

默认 dry-run 调用 Pktgen/TRex 工具不触发 interrupt 且不连接硬件
（结果 mode=dry_run）；--trex-explore 工具集仅含 2 个 TRex 工具且全程
无 interrupt（FR-012/FR-019、SC-010）。全部 mock 网络 I/O（R11）。
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from langchain_core.messages import AIMessage

ALLOWED_IP = "10.99.80.160"


class TestPktgenDryRun:
    def test_pktgen_dry_run_no_interrupt(self):
        from src.pktgen import adapter

        with patch.object(adapter, "interrupt") as mock_int, \
             patch.object(adapter, "_execute_skill") as mock_exec:
            mock_exec.return_value = {"success": True, "mode": "dry_run"}
            result = adapter.pktgen_udp_flood.invoke({
                "dst_ip": ALLOWED_IP, "rate": 50,
            })

        assert result["mode"] == "dry_run"
        mock_int.assert_not_called()  # 零审批

    def test_pktgen_dry_run_no_hardware_connection(self):
        """dry-run 只编译：execute_skill_live 绝不调用（零连接）。"""
        from src.pktgen import adapter

        with patch.object(adapter, "is_dry_run", return_value=True), \
             patch.object(adapter, "_import_pktgen") as mock_imp:
            mock_dry = MagicMock(return_value={"success": True, "mode": "dry_run"})
            mock_live = MagicMock()
            mock_imp.return_value = (mock_dry, mock_live)

            adapter.pktgen_udp_flood.invoke({"dst_ip": ALLOWED_IP, "rate": 50})

            mock_dry.assert_called_once()
            mock_live.assert_not_called()


class TestTrexDryRun:
    def test_trex_dry_run_no_interrupt_no_execution(self, tmp_path, monkeypatch):
        from src.trex import tools as trex_tools

        monkeypatch.setattr(trex_tools, "get_trex_scripts_dir", lambda: tmp_path)
        monkeypatch.setattr(trex_tools, "is_trex_dry_run", lambda: True)
        (tmp_path / "s.py").write_text(f"target = '{ALLOWED_IP}'\n",
                                       encoding="utf-8")

        with patch.object(trex_tools, "interrupt") as mock_int, \
             patch.object(trex_tools, "subprocess") as mock_sub:
            result = trex_tools.run_python_file.invoke({
                "filename": "s.py", "target_ip": ALLOWED_IP,
            })

        assert result["mode"] == "dry_run"
        mock_int.assert_not_called()
        mock_sub.run.assert_not_called()


class TestExploreModeZeroApproval:
    def test_explore_toolset_only_trex(self):
        from src.agent import graph as graph_mod
        from src.trex.tools import TREX_TOOLS

        captured = {}

        def fake_create_agent(**kwargs):
            captured.update(kwargs)
            return object()

        with patch.object(graph_mod, "_build_model", return_value=object()), \
             patch.object(graph_mod, "create_agent", side_effect=fake_create_agent):
            graph_mod.build_graph(mode="catalog", max_iters=40)

        assert captured["tools"] == TREX_TOOLS
        assert len(captured["tools"]) == 2

    def test_explore_run_zero_interrupt(self, tmp_path, monkeypatch):
        """catalog 模式真实 graph + fake 模型：全程零 interrupt、零审批。"""
        from src.agent import graph as graph_mod
        from src.trex import tools as trex_tools

        monkeypatch.setattr(trex_tools, "get_trex_scripts_dir", lambda: tmp_path)
        monkeypatch.setenv("TREX_DRY_RUN", "true")

        model = MagicMock()
        model.model_name = "deepseek-chat"
        model.bind_tools.return_value = model
        model.invoke.side_effect = [
            AIMessage(content="规划完毕", tool_calls=[{
                "name": "write_python_file",
                "args": {"filename": "cat_udp.py",
                         "code": "import trex_stl_lib\nprint('ok')\n"},
                "id": "c1",
            }]),
            AIMessage(content="目录总结完成。"),
        ]

        with patch.object(graph_mod, "_build_model", return_value=model), \
             patch.object(trex_tools, "interrupt") as mock_int:
            graph = graph_mod.build_graph(mode="catalog", max_iters=40)
            result = graph.invoke(
                {"messages": [{"role": "user", "content": "探索 TRex 攻击能力"}]},
                {"configurable": {"thread_id": "explore-016"}},
            )

        mock_int.assert_not_called()  # 全程零审批
        assert (tmp_path / "cat_udp.py").exists()
        assert result is not None
