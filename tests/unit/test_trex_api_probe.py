"""Unit tests for scripts/trex_api_probe.py.

本环境未安装 TRex 客户端库，因此这里验证的是「优雅降级」路径：
顶层导入不依赖 trex 库、detect_layout() 返回空布局、main() 输出清晰
诊断并以退出码 1 结束。真实库的探测在 trex311 环境里运行验证。
"""
import pytest

import scripts.trex_api_probe as probe


class TestDetectLayoutWithoutTrex:
    def test_returns_empty_layout(self):
        result = probe.detect_layout()
        assert result["layout"] is None
        assert result["stl"] is None
        assert result["astf"] is None
        assert result["stl_module"] is None
        assert result["astf_module"] is None

    def test_versions_empty(self):
        layout = probe.detect_layout()
        assert probe.collect_versions(layout) == []


class TestMainWithoutTrex:
    def test_exit_code_1_and_diagnostic(self, capsys):
        rc = probe.main([])
        out = capsys.readouterr().out
        assert rc == 1
        assert "未找到任何 TRex 客户端库" in out
        assert "trex311" in out  # 指引指向实验床的 trex.python

    def test_exit_code_0_with_fake_layout(self, capsys):
        """渲染器对合法探测结果应正常工作（用假模块模拟命中）。"""
        fake_stl = type("fake_stl", (), {
            "STLClient": type("STLClient", (), {
                "connect": lambda self: None,
                "start": lambda self, ports=None, mult="100%", duration=10, force=False: None,
                "__doc__": "STL 客户端",
            }),
            "__doc__": "fake stl api",
        })()
        fake_astf = type("fake_astf", (), {
            "ASTFClient": type("ASTFClient", (), {
                "load_profile": lambda self, profile_path: None,
                "__doc__": "ASTF 客户端",
            }),
            "ASTFTCPClientTemplate": type("ASTFTCPClientTemplate", (), {
                "__doc__": "ASTF TCP 客户端模板",
            }),
            "__doc__": "fake astf api",
        })()
        layout = {
            "layout": "v3",
            "note": "fake",
            "stl_module": "trex.stl.api",
            "astf_module": "trex.astf.api",
            "stl": fake_stl,
            "astf": fake_astf,
        }
        stl_rows, stl_missing = probe._probe(
            fake_stl, [("STLClient", ["connect", "start"])],
        )
        astf_rows, astf_missing = probe._probe(
            fake_astf,
            [("ASTFClient", ["load_profile"]), ("ASTFTCPClientTemplate", None)],
        )
        ctx = {
            "generated_at": "2026-11-24T00:00:00+08:00",
            "interpreter": "python",
            "python": "3.11",
            "layout": layout,
            "versions": [("pip dist trex", "3.08")],
            "expect": "3.08",
            "expect_ok": True,
            "server": "",
            "server_status": "error",
            "stl_section": {"rows": stl_rows, "missing": stl_missing, "index": ""},
            "astf_section": {"rows": astf_rows, "missing": astf_missing, "index": ""},
        }
        report = probe.render_report(ctx)
        assert "STLClient" in report
        assert "ASTFTCPClientTemplate" in report
        assert "期望版本检查: ✓" in report
        assert "未找到的符号" in report


class TestProbeServerVersion:
    def test_no_modules_returns_error(self):
        layout = {"layout": None, "stl_module": None, "astf_module": None,
                  "stl": None, "astf": None}
        text, status = probe.probe_server_version(layout, "10.0.0.1", 4501)
        assert status == "error"
        assert "无可用客户端" in text

    def test_child_success_path(self, monkeypatch):
        class FakeProc:
            returncode = 0
            stdout = "{'version': 'v3.08'}"
            stderr = ""

        monkeypatch.setattr(probe.subprocess, "run", lambda *a, **k: FakeProc())
        layout = {"layout": "v3", "stl_module": "trex.stl.api",
                  "astf_module": "trex.astf.api", "stl": None, "astf": None}
        text, status = probe.probe_server_version(layout, "10.0.0.1", 4501)
        assert status == "ok"
        assert "ASTFClient" in text and "v3.08" in text

    def test_child_timeout_path(self, monkeypatch):
        import subprocess

        def fake_run(*a, **k):
            raise subprocess.TimeoutExpired(cmd="python", timeout=15)

        monkeypatch.setattr(probe.subprocess, "run", fake_run)
        layout = {"layout": "v3", "stl_module": "trex.stl.api",
                  "astf_module": "trex.astf.api", "stl": None, "astf": None}
        text, status = probe.probe_server_version(layout, "10.0.0.1", 4501)
        assert status == "error"
        assert "超时" in text


class TestHelpers:
    def test_signature_fallback_returns_placeholder(self):
        class NoSig:
            pass

        assert isinstance(probe._signature(NoSig), str)

    def test_doc_first_line_truncates(self):
        long_doc = "x" * 300
        result = probe._doc_first_line(type("T", (), {"__doc__": long_doc}))
        assert result.endswith("…")
        assert len(result) <= 201

    def test_module_index_filters_astf_stl(self):
        fake = type("fake", (), {})()
        fake.STLClient = None
        fake.FOO = None
        fake.ASTFProfile = None
        text = probe._module_index(fake)
        assert "STLClient" in text
        assert "ASTFProfile" in text
        assert "FOO" not in text
