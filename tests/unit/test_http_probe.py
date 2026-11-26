"""Unit tests for HTTP dial-testing (probe, curl parsing, observation window)."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.tools.http_probe_tool import (
    _classify_error,
    _run_curl,
    http_probe,
    validate_http_url,
)
from src.tools.http_window import build_http_observation


# ── validate_http_url ─────────────────────────────────────────────

class TestValidateHttpUrl:
    def test_rejects_non_allowlisted_ip(self):
        with pytest.raises(ValueError):
            validate_http_url("http://192.168.1.99:8080/")

    def test_accepts_allowlisted_ip(self):
        assert validate_http_url("http://10.99.80.160:8080/") == "10.99.80.160"

    def test_rejects_bad_scheme(self):
        with pytest.raises(ValueError):
            validate_http_url("ftp://10.99.80.160/")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            validate_http_url("")


# ── _classify_error ───────────────────────────────────────────────

class TestClassifyError:
    def test_success_is_none(self):
        assert _classify_error(0) is None

    def test_timeout(self):
        assert _classify_error(28) == "timeout"

    def test_connection_refused(self):
        assert _classify_error(7) == "connection_refused"

    def test_dns_error(self):
        assert _classify_error(6) == "dns_error"

    def test_tls_error(self):
        assert _classify_error(35) == "tls_error"

    def test_other(self):
        assert _classify_error(1) == "other"


# ── _run_curl ─────────────────────────────────────────────────────

class TestRunCurl:
    def test_parses_success_output(self):
        stdout = "0.001|0.002|0.003|0.010|0.015|200|1234|82000.0"
        with patch("src.tools.http_probe_tool.subprocess.run") as mock_run, \
             patch("src.tools.http_probe_tool._curl_available", return_value=True):
            mock_run.return_value = SimpleNamespace(returncode=0, stdout=stdout, stderr="")
            result = _run_curl("http://10.99.80.160/")

        assert result["success"] is True
        assert result["status_code"] == 200
        assert result["ttfb_ms"] == 10.0
        assert result["total_ms"] == 15.0
        assert result["dns_ms"] == 1.0
        assert result["size_bytes"] == 1234

    def test_timeout_error(self):
        with patch("src.tools.http_probe_tool.subprocess.run") as mock_run, \
             patch("src.tools.http_probe_tool._curl_available", return_value=True):
            mock_run.return_value = SimpleNamespace(returncode=28, stdout="", stderr="timeout")
            result = _run_curl("http://10.99.80.160/")

        assert result["success"] is False
        assert result["error_type"] == "timeout"

    def test_post_body_and_content_type(self):
        """POST 带 body/content_type 时，curl 命令应含 -d 与 Content-Type。"""
        stdout = "0|0|0|0.010|0.015|200|0|0"
        with patch("src.tools.http_probe_tool.subprocess.run") as mock_run, \
             patch("src.tools.http_probe_tool._curl_available", return_value=True):
            mock_run.return_value = SimpleNamespace(returncode=0, stdout=stdout, stderr="")
            _run_curl(
                "http://10.99.80.160/api/auth/login", method="POST",
                body='{"email":"a","password":"b"}', content_type="application/json",
            )

        cmd = mock_run.call_args[0][0]
        assert "-d" in cmd
        assert '{"email":"a","password":"b"}' in cmd
        assert "Content-Type: application/json" in cmd

    def test_curl_missing(self):
        with patch("src.tools.http_probe_tool._curl_available", return_value=False):
            result = _run_curl("http://10.99.80.160/")
        assert result["success"] is False
        assert result["error_type"] == "curl_missing"

    def test_command_forces_noproxy(self):
        """Probes must bypass the environment's http_proxy (internal hosts)."""
        with patch("src.tools.http_probe_tool.subprocess.run") as mock_run, \
             patch("src.tools.http_probe_tool._curl_available", return_value=True):
            mock_run.return_value = SimpleNamespace(returncode=0, stdout="0.001|0.002|0|0|0|200|1|1.0", stderr="")
            _run_curl("http://10.99.80.160/")

        cmd = mock_run.call_args[0][0]
        assert "--noproxy" in cmd
        assert "*" in cmd


# ── http_probe (validation gate) ──────────────────────────────────

class TestHttpProbe:
    def test_rejects_non_allowlisted_url_before_curl(self):
        result = http_probe("http://192.168.1.99:8080/")
        assert result["success"] is False
        assert "error" in result


# ── build_http_observation ────────────────────────────────────────

class _FakeMonitor:
    def __init__(self, samples):
        self._samples = samples

    def is_running(self):
        return True

    def get_samples_since(self, t0):
        return self._samples


class TestBuildHttpObservation:
    def test_monitor_not_running(self):
        m = SimpleNamespace(is_running=lambda: False)
        result = build_http_observation(m, 0, "scapy")
        assert result["http_during"] is None
        assert result["http_observation_window"]["covers_attack_window"] is False

    def test_with_samples(self):
        samples = [
            {"ts": 1.0, "ttfb_ms": 10.0, "total_ms": 15.0, "status_code": 200,
             "success": True, "error_type": None},
            {"ts": 1.5, "ttfb_ms": None, "total_ms": None, "status_code": None,
             "success": False, "error_type": "timeout"},
            {"ts": 2.0, "ttfb_ms": 30.0, "total_ms": 40.0, "status_code": 503,
             "success": True, "error_type": None},
        ]
        result = build_http_observation(_FakeMonitor(samples), 0, "scapy")

        d = result["http_during"]
        assert d["total_requests"] == 3
        assert d["success_rate"] == pytest.approx(2 / 3, abs=0.001)
        assert d["timeout_count"] == 1
        assert d["avg_ttfb_ms"] == 20.0  # (10 + 30) / 2
        assert d["five_xx_rate"] == pytest.approx(1 / 3, abs=0.001)
        assert d["samples"] == samples  # 每请求时间序列原样透出，供曲线展示
        assert d["status_codes"] == {200: 1, 503: 1}

    def test_empty_samples(self):
        result = build_http_observation(_FakeMonitor([]), 0, "scapy")
        assert result["http_during"] is None
