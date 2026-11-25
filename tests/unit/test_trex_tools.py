"""Unit tests for the TRex client tools (write_python_file / run_python_file).

All I/O is mocked; no real files, subprocess, or network access.
"""
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from src.trex.tools import (
    write_python_file,
    run_python_file,
    _resolve_script_path,
    _static_ip_guard,
)

ALLOWLISTED_IP = "10.99.80.160"
NOT_ALLOWLISTED_IP = "192.168.1.99"


# ── _resolve_script_path sandbox ────────────────────────────────────

class TestResolveScriptPath:
    def test_rejects_traversal(self):
        with pytest.raises(ValueError):
            _resolve_script_path("../evil.py")

    def test_rejects_absolute_and_backslash(self):
        with pytest.raises(ValueError):
            _resolve_script_path("/etc/evil.py")
        with pytest.raises(ValueError):
            _resolve_script_path("..\\evil.py")

    def test_rejects_non_py_and_empty_and_hidden(self):
        with pytest.raises(ValueError):
            _resolve_script_path("evil.txt")
        with pytest.raises(ValueError):
            _resolve_script_path("")
        with pytest.raises(ValueError):
            _resolve_script_path(".hidden.py")

    def test_accepts_bare_name(self):
        path = _resolve_script_path("ok.py")
        assert path.name == "ok.py"
        assert path.parent.name == "trex_scripts"


# ── write_python_file ───────────────────────────────────────────────

class TestWritePythonFile:
    def test_writes_valid_code_and_syntax_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        result = write_python_file.invoke({"filename": "ok.py", "code": "print('ok')\n"})
        assert result["success"] is True
        assert result["syntax_ok"] is True
        assert result["syntax_error"] is None
        assert (tmp_path / "ok.py").exists()

    def test_syntax_error_still_writes_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        result = write_python_file.invoke(
            {"filename": "bad.py", "code": "def broken(:\n"}
        )
        assert result["success"] is True
        assert result["syntax_ok"] is False
        assert result["syntax_error"]
        assert (tmp_path / "bad.py").exists()  # file preserved for human fix

    def test_rejects_oversized_code(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        result = write_python_file.invoke(
            {"filename": "big.py", "code": "x = 1\n" * 5000}
        )
        assert result["success"] is False
        assert "lines" in result["error"]

    def test_rejects_too_many_chars(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        result = write_python_file.invoke(
            {"filename": "x.py", "code": "x" * 100_001}
        )
        assert result["success"] is False
        assert "chars" in result["error"]

    def test_write_oserror(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            result = write_python_file.invoke(
                {"filename": "x.py", "code": "print(1)\n"}
            )
        assert result["success"] is False
        assert "failed to write" in result["error"]


# ── run_python_file ─────────────────────────────────────────────────

class TestRunPythonFile:
    def _write(self, tmp_path, name="s.py", code="print('ok')\n"):
        (tmp_path / name).write_text(code, encoding="utf-8")
        return tmp_path / name

    def test_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        result = run_python_file.invoke({"filename": "nope.py"})
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_target_ip_not_allowlisted(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        self._write(tmp_path)
        result = run_python_file.invoke(
            {"filename": "s.py", "target_ip": NOT_ALLOWLISTED_IP}
        )
        assert result["success"] is False
        assert "not in allowlist" in result["error"]

    def test_dry_run_does_not_execute(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        monkeypatch.setattr("src.trex.tools.is_trex_dry_run", lambda: True)
        self._write(tmp_path)
        with patch("src.trex.tools.subprocess.run") as mock_run:
            result = run_python_file.invoke(
                {"filename": "s.py", "target_ip": ALLOWLISTED_IP}
            )
        assert result["mode"] == "dry_run"
        mock_run.assert_not_called()

    def test_live_non_allowlisted_ip_shown_in_hitl(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        monkeypatch.setattr("src.trex.tools.is_trex_dry_run", lambda: False)
        self._write(tmp_path, code=f"target = '{NOT_ALLOWLISTED_IP}'\n")
        with patch("src.trex.tools.interrupt", return_value=True) as mock_int, \
             patch("src.trex.tools.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            result = run_python_file.invoke({"filename": "s.py"})
        # 不再硬拦截：进入 HITL，且 HITL 参数里提示非 allowlist IP
        assert result["success"] is True
        hitl_params = mock_int.call_args[0][0]["params"]
        assert NOT_ALLOWLISTED_IP in hitl_params["non_allowlisted_ips"]

    def test_live_hitl_gate(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        monkeypatch.setattr("src.trex.tools.is_trex_dry_run", lambda: False)
        self._write(tmp_path, code=f"target = '{ALLOWLISTED_IP}'\n")
        with patch("src.trex.tools.interrupt", return_value=True), \
             patch("src.trex.tools.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            result = run_python_file.invoke(
                {"filename": "s.py", "target_ip": ALLOWLISTED_IP}
            )
        assert result["success"] is True
        assert result["mode"] == "live"
        mock_run.assert_called_once()

    def test_live_nonzero_exit_reports_stderr(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        monkeypatch.setattr("src.trex.tools.is_trex_dry_run", lambda: False)
        self._write(tmp_path)
        with patch("src.trex.tools.interrupt", return_value=True), \
             patch("src.trex.tools.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="boom"
            )
            result = run_python_file.invoke(
                {"filename": "s.py", "target_ip": ALLOWLISTED_IP}
            )
        assert result["success"] is False
        assert result["stderr"] == "boom"
        assert "exited with code 1" in result["error"]

    def test_live_timeout(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        monkeypatch.setattr("src.trex.tools.is_trex_dry_run", lambda: False)
        self._write(tmp_path)
        with patch("src.trex.tools.interrupt", return_value=True), \
             patch("src.trex.tools.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd="python", timeout=30, output="connected\nacquired\n", stderr=""
            )
            result = run_python_file.invoke(
                {"filename": "s.py", "target_ip": ALLOWLISTED_IP}
            )
        assert result["success"] is False
        assert "timed out" in result["error"]
        assert result["stdout"] == "connected\nacquired\n"
        assert result["stderr"] == ""

    def test_live_strips_proxy_env(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        monkeypatch.setattr("src.trex.tools.is_trex_dry_run", lambda: False)
        self._write(tmp_path)
        monkeypatch.setenv("http_proxy", "http://10.99.80.152:8889")
        monkeypatch.setenv("https_proxy", "http://10.99.80.152:8889")
        monkeypatch.setenv("SOME_KEEP", "kept")
        with patch("src.trex.tools.interrupt", return_value=True), \
             patch("src.trex.tools.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            run_python_file.invoke({"filename": "s.py", "target_ip": ALLOWLISTED_IP})
        env = mock_run.call_args.kwargs["env"]
        assert "http_proxy" not in env
        assert "https_proxy" not in env
        assert "all_proxy" not in env
        assert "HTTP_PROXY" not in env
        assert env["SOME_KEEP"] == "kept"

    def test_live_hitl_reject(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        monkeypatch.setattr("src.trex.tools.is_trex_dry_run", lambda: False)
        self._write(tmp_path)
        with patch("src.trex.tools.interrupt", return_value=False), \
             patch("src.trex.tools.subprocess.run") as mock_run:
            result = run_python_file.invoke(
                {"filename": "s.py", "target_ip": ALLOWLISTED_IP}
            )
        assert result["success"] is False
        assert "HITL rejected" in result["error"]
        mock_run.assert_not_called()

    def test_live_subprocess_oserror(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        monkeypatch.setattr("src.trex.tools.is_trex_dry_run", lambda: False)
        self._write(tmp_path)
        with patch("src.trex.tools.interrupt", return_value=True), \
             patch("src.trex.tools.subprocess.run", side_effect=OSError("no python")):
            result = run_python_file.invoke(
                {"filename": "s.py", "target_ip": ALLOWLISTED_IP}
            )
        assert result["success"] is False
        assert "failed to run script" in result["error"]

    def test_live_blocks_syntax_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        monkeypatch.setattr("src.trex.tools.is_trex_dry_run", lambda: False)
        self._write(tmp_path, code="def broken(:\n")
        result = run_python_file.invoke({"filename": "s.py"})
        assert result["success"] is False
        assert "syntax error" in result["error"]


# ── _static_ip_guard ────────────────────────────────────────────────

class TestStaticIpGuard:
    def test_excludes_allowlisted_loopback_and_server_host(self):
        with patch("src.trex.tools.get_trex_host", return_value="10.99.80.222"):
            code = (
                f"a = '{ALLOWLISTED_IP}'\n"    # allowlisted
                "b = '127.0.0.1'\n"            # loopback
                "c = '10.99.80.222'\n"         # TRex server host
            )
            assert _static_ip_guard(code) == []

    def test_flags_non_allowlisted_ip(self):
        with patch("src.trex.tools.get_trex_host", return_value="10.99.80.222"):
            code = f"x = '{NOT_ALLOWLISTED_IP}'\n"
            assert _static_ip_guard(code) == [NOT_ALLOWLISTED_IP]


# ── reserved helper name ────────────────────────────────────────────

class TestReservedHelperName:
    def test_write_python_file_rejects_trex_common(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        result = write_python_file.invoke(
            {"filename": "trex_common.py", "code": "x = 1\n"}
        )
        assert result["success"] is False
        assert "reserved" in result["error"]

    def test_script_importing_trex_common_is_syntax_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.trex.tools.get_trex_scripts_dir", lambda: tmp_path)
        result = write_python_file.invoke(
            {"filename": "cat_x.py",
             "code": "from trex_common import DST_MAC, SRC_MAC, start_safe\n"}
        )
        assert result["success"] is True
        assert result["syntax_ok"] is True
