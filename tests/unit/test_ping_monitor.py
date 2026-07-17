"""Tests for PingMonitor — continuous background ping + fping monitoring."""

import sys
import time
from unittest.mock import patch, MagicMock
import pytest

from src.tools.ping_monitor import (
    PingMonitor,
    MonitorSample,
    _extract_rtt,
    _is_loss_line,
    _FPING_SUCCESS_RE,
    _FPING_TIMEOUT_RE,
    get_ping_monitor,
)

ALLOWLISTED_IP = "10.99.80.160"


class TestPingMonitorInit:
    """Tests for PingMonitor initialization and singleton."""

    def test_initial_state_not_running(self):
        monitor = PingMonitor()
        assert monitor.is_running() is False
        assert monitor.target_ip is None

    def test_singleton_returns_same_instance(self):
        m1 = get_ping_monitor()
        m2 = get_ping_monitor()
        assert m1 is m2
        assert isinstance(m1, PingMonitor)

    def test_start_stores_target_ip(self):
        monitor = PingMonitor()
        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.stdout = MagicMock()
            mock_process.stdout.readline.side_effect = ["", Exception("stop")]
            mock_popen.return_value = mock_process

            monitor.start(ALLOWLISTED_IP)
            assert monitor.target_ip == ALLOWLISTED_IP
            monitor.stop()


class TestPingMonitorCmdBuilding:
    """Tests for platform-specific ping command building."""

    def test_linux_ping_cmd(self):
        with patch.object(sys, "platform", "linux"):
            monitor = PingMonitor()
            cmd = monitor._build_ping_cmd(ALLOWLISTED_IP, 1.0)
            assert "ping" in cmd[0]
            assert "-c" not in cmd
            assert ALLOWLISTED_IP in cmd

    def test_windows_ping_cmd(self):
        with patch.object(sys, "platform", "win32"):
            monitor = PingMonitor()
            cmd = monitor._build_ping_cmd(ALLOWLISTED_IP, 1.0)
            assert "-t" in cmd
            assert ALLOWLISTED_IP in cmd

    def test_fping_cmd_on_linux(self):
        with patch.object(sys, "platform", "linux"), \
             patch("src.tools.ping_monitor._fping_available", return_value=True):
            monitor = PingMonitor()
            cmd = monitor._build_fping_cmd(ALLOWLISTED_IP, 1.0)
            assert cmd[0] == "fping"
            assert "-l" in cmd
            assert ALLOWLISTED_IP in cmd


class TestPingMonitorParsing:
    """Tests for ping output line parsing."""

    def test_extract_rtt_linux_reply(self):
        rtt = _extract_rtt(
            "64 bytes from 10.99.80.160: icmp_seq=1 ttl=64 time=12.345 ms"
        )
        assert rtt == 12.345

    def test_extract_rtt_windows_reply(self):
        rtt = _extract_rtt(
            "Reply from 10.99.80.160: bytes=32 time=8ms TTL=64"
        )
        assert rtt == 8.0

    def test_extract_rtt_timeout_returns_none(self):
        assert _extract_rtt("Request timed out.") is None
        assert _extract_rtt("Request timeout for icmp_seq 1") is None

    def test_extract_rtt_summary_returns_none(self):
        assert _extract_rtt("--- 10.99.80.160 ping statistics ---") is None

    def test_extract_rtt_empty_returns_none(self):
        assert _extract_rtt("") is None
        assert _extract_rtt("   ") is None

    # ── MonitorSample creation via _parse_ping_line ──────────────────

    def test_parse_ping_line_success(self):
        monitor = PingMonitor()
        sample = monitor._parse_ping_line(
            "64 bytes from 10.99.80.160: icmp_seq=1 ttl=64 time=12.345 ms"
        )
        assert sample is not None
        assert sample.rtt_ms == 12.345
        assert sample.sent == 1
        assert sample.received == 1

    def test_parse_ping_line_timeout(self):
        monitor = PingMonitor()
        sample = monitor._parse_ping_line("Request timed out.")
        assert sample is not None
        assert sample.rtt_ms is None
        assert sample.sent == 1
        assert sample.received == 0

    def test_parse_ping_line_unreachable(self):
        monitor = PingMonitor()
        sample = monitor._parse_ping_line(
            "Reply from 10.99.80.1: Destination host unreachable."
        )
        assert sample is not None
        assert sample.received == 0

    def test_parse_ping_line_non_probe_returns_none(self):
        monitor = PingMonitor()
        assert monitor._parse_ping_line("") is None
        assert monitor._parse_ping_line("PING 10.99.80.160 ...") is None

    # ── Loss line detection ─────────────────────────────────────────

    def test_loss_line_timeout(self):
        assert _is_loss_line("Request timed out.") is True
        assert _is_loss_line("Request timed out") is True

    def test_loss_line_unreachable(self):
        assert _is_loss_line("Destination host unreachable.") is True
        assert _is_loss_line("Reply from X: Destination host unreachable.") is True

    def test_loss_line_chinese_windows(self):
        assert _is_loss_line("请求超时。") is True

    def test_loss_line_success_is_not_loss(self):
        assert _is_loss_line(
            "64 bytes from 10.99.80.160: icmp_seq=1 ttl=64 time=12.345 ms"
        ) is False


class TestFpingParsing:
    """Tests for fping output line parsing."""

    def test_fping_success_line(self):
        line = "10.99.80.160 : [0], 84 bytes, 2.12 ms (2.12 avg, 0% loss)"
        m = _FPING_SUCCESS_RE.search(line)
        assert m is not None
        assert float(m.group(1)) == 2.12

    def test_fping_timeout_line(self):
        line = "10.99.80.160 : [1], 84 bytes, timeout (2.12 avg, 50% loss)"
        m = _FPING_TIMEOUT_RE.search(line)
        assert m is not None

    def test_parse_fping_line_success(self):
        monitor = PingMonitor()
        sample = monitor._parse_fping_line(
            "10.99.80.160 : [0], 84 bytes, 2.12 ms (2.12 avg, 0% loss)"
        )
        assert sample is not None
        assert sample.rtt_ms == 2.12
        assert sample.sent == 1
        assert sample.received == 1

    def test_parse_fping_line_timeout(self):
        monitor = PingMonitor()
        sample = monitor._parse_fping_line(
            "10.99.80.160 : [1], 84 bytes, timeout (2.12 avg, 50% loss)"
        )
        assert sample is not None
        assert sample.rtt_ms is None
        assert sample.sent == 1
        assert sample.received == 0

    def test_parse_fping_line_icmp_host_skipped(self):
        monitor = PingMonitor()
        assert monitor._parse_fping_line(
            "ICMP Host Unreachable from 192.168.1.1 for ICMP Echo sent to 10.99.80.160"
        ) is None

    def test_parse_fping_line_empty(self):
        monitor = PingMonitor()
        assert monitor._parse_fping_line("") is None
        assert monitor._parse_fping_line("   ") is None


class TestFpingQ:
    """Tests for fping -Q periodic summary backend."""

    def test_build_fping_q_cmd(self):
        monitor = PingMonitor()
        cmd = monitor._build_fping_q_cmd(ALLOWLISTED_IP)
        assert cmd[0] == "fping"
        assert "-l" in cmd
        assert "-Q" in cmd
        assert "1" in cmd
        assert "-p" in cmd
        assert "100" in cmd
        assert ALLOWLISTED_IP in cmd

    def test_parse_summary_normal(self):
        monitor = PingMonitor()
        sample = monitor._parse_fping_summary_line(
            "10.99.80.160 : xmt/rcv/%loss = 10/10/0%, min/avg/max = 1.5/2.3/3.1"
        )
        assert sample is not None
        assert sample.rtt_ms == 2.3  # avg
        assert sample.sent == 10
        assert sample.received == 10

    def test_parse_summary_with_loss(self):
        monitor = PingMonitor()
        sample = monitor._parse_fping_summary_line(
            "10.99.80.160 : xmt/rcv/%loss = 10/6/40%, min/avg/max = 2.1/5.7/12.3"
        )
        assert sample is not None
        assert sample.rtt_ms == 5.7
        assert sample.sent == 10
        assert sample.received == 6

    def test_parse_summary_all_lost(self):
        monitor = PingMonitor()
        sample = monitor._parse_fping_summary_line(
            "10.99.80.160 : xmt/rcv/%loss = 10/0/100%, min/avg/max = 0/0/0"
        )
        assert sample is not None
        assert sample.rtt_ms == 0.0
        assert sample.sent == 10
        assert sample.received == 0

    def test_parse_summary_empty(self):
        monitor = PingMonitor()
        assert monitor._parse_fping_summary_line("") is None
        assert monitor._parse_fping_summary_line("   ") is None

    def test_parse_summary_icmp_host_line(self):
        monitor = PingMonitor()
        assert monitor._parse_fping_summary_line(
            "ICMP Host Unreachable from 192.168.1.1 for ICMP Echo sent to 10.99.80.160"
        ) is None


class TestPingMonitorStats:
    """Tests for get_stats and get_samples_since."""

    def _make_monitor_with_samples(self, samples: list[MonitorSample]):
        """Helper: create a monitor with pre-loaded MonitorSample entries."""
        monitor = PingMonitor()
        monitor._running = True
        monitor._target_ip = ALLOWLISTED_IP
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        monitor._process = mock_proc
        for s in samples:
            monitor._samples.append(s)
        return monitor

    def test_get_stats_returns_correct_average(self):
        now = time.time()
        monitor = self._make_monitor_with_samples([
            MonitorSample(ts=now - 3, rtt_ms=10.0),
            MonitorSample(ts=now - 2, rtt_ms=20.0),
            MonitorSample(ts=now - 1, rtt_ms=30.0),
        ])

        stats = monitor.get_stats(window_s=10)
        assert stats["avg_rtt_ms"] == 20.0
        assert stats["min_rtt_ms"] == 10.0
        assert stats["max_rtt_ms"] == 30.0
        assert stats["sample_count"] == 3
        assert stats["sent_count"] == 3
        assert stats["loss_pct"] == 0.0
        assert "backend" in stats

    def test_get_stats_with_loss(self):
        """丢包率应从窗口内 sent/received 正确计算。"""
        now = time.time()
        monitor = self._make_monitor_with_samples([
            MonitorSample(ts=now - 4, rtt_ms=10.0, sent=1, received=1),
            MonitorSample(ts=now - 3, rtt_ms=None, sent=1, received=0),  # lost
            MonitorSample(ts=now - 2, rtt_ms=20.0, sent=1, received=1),
            MonitorSample(ts=now - 1, rtt_ms=None, sent=1, received=0),  # lost
        ])

        stats = monitor.get_stats(window_s=10)
        assert stats["sent_count"] == 4
        assert stats["sample_count"] == 2  # received
        assert stats["loss_pct"] == 50.0
        assert stats["avg_rtt_ms"] == 15.0

    def test_get_stats_empty_returns_defaults(self):
        monitor = PingMonitor()
        monitor._running = True
        monitor._target_ip = ALLOWLISTED_IP
        # Mock process so is_running() returns True
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        monitor._process = mock_proc

        stats = monitor.get_stats(window_s=10)
        assert stats["sample_count"] == 0
        assert stats["sent_count"] == 0
        assert stats["loss_pct"] == 0.0  # no sent probes → 0% loss

    def test_get_stats_respects_window(self):
        now = time.time()
        monitor = self._make_monitor_with_samples([
            MonitorSample(ts=now - 10, rtt_ms=5.0),
            MonitorSample(ts=now - 3, rtt_ms=10.0),
            MonitorSample(ts=now - 1, rtt_ms=30.0),
        ])

        stats = monitor.get_stats(window_s=5)
        assert stats["sample_count"] == 2
        assert stats["avg_rtt_ms"] == 20.0

    def test_get_samples_since_returns_filtered(self):
        now = time.time()
        monitor = self._make_monitor_with_samples([
            MonitorSample(ts=now - 10, rtt_ms=5.0),
            MonitorSample(ts=now - 3, rtt_ms=10.0),
            MonitorSample(ts=now - 1, rtt_ms=30.0),
        ])

        samples = monitor.get_samples_since(now - 5)
        assert len(samples) == 2
        assert samples[0]["rtt_ms"] == 10.0
        assert samples[1]["rtt_ms"] == 30.0

    def test_get_samples_since_empty_when_no_new_data(self):
        now = time.time()
        monitor = self._make_monitor_with_samples([
            MonitorSample(ts=now - 10, rtt_ms=5.0),
        ])

        samples = monitor.get_samples_since(now - 1)
        assert len(samples) == 0

    def test_get_samples_since_all_after_cutoff(self):
        monitor = PingMonitor()
        monitor._running = True
        monitor._target_ip = ALLOWLISTED_IP
        t0 = time.time()
        monitor._samples.append(MonitorSample(ts=t0 - 0.01, rtt_ms=5.0))
        monitor._samples.append(MonitorSample(ts=t0, rtt_ms=10.0))
        monitor._samples.append(MonitorSample(ts=t0 + 0.01, rtt_ms=15.0))

        samples = monitor.get_samples_since(t0)
        assert len(samples) == 1
        assert samples[0]["rtt_ms"] == 15.0

    def test_get_samples_since_includes_sent_received(self):
        """get_samples_since 应返回 sent/received 字段。"""
        now = time.time()
        monitor = self._make_monitor_with_samples([
            MonitorSample(ts=now - 2, rtt_ms=10.0, sent=1, received=1),
            MonitorSample(ts=now - 1, rtt_ms=None, sent=1, received=0),
        ])

        samples = monitor.get_samples_since(0)
        assert samples[0]["sent"] == 1
        assert samples[0]["received"] == 1
        assert samples[1]["sent"] == 1
        assert samples[1]["received"] == 0
        assert samples[1]["rtt_ms"] is None

    def test_get_stats_not_running_returns_empty(self):
        monitor = PingMonitor()
        stats = monitor.get_stats(window_s=5)
        assert stats["sample_count"] == 0
        assert stats["monitor_active"] is False
        assert stats["loss_pct"] == 100.0

    def test_get_stats_all_lost(self):
        """全丢包时 loss_pct 应为 100。"""
        now = time.time()
        monitor = self._make_monitor_with_samples([
            MonitorSample(ts=now - 2, rtt_ms=None, sent=1, received=0),
            MonitorSample(ts=now - 1, rtt_ms=None, sent=1, received=0),
        ])

        stats = monitor.get_stats(window_s=10)
        assert stats["loss_pct"] == 100.0
        assert stats["sample_count"] == 0
        assert stats["sent_count"] == 2


class TestPingMonitorStop:
    """Tests for stop and cleanup."""

    def test_stop_kills_process(self):
        monitor = PingMonitor()
        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.stdout = MagicMock()
            mock_process.stdout.readline.side_effect = ["", Exception("stop")]
            mock_process.poll.return_value = None
            mock_popen.return_value = mock_process

            monitor.start(ALLOWLISTED_IP)
            monitor.stop()

            mock_process.terminate.assert_called()
            assert monitor.is_running() is False
            assert monitor.target_ip is None

    def test_stop_when_not_running_is_safe(self):
        monitor = PingMonitor()
        monitor.stop()
        assert monitor.is_running() is False

    def test_start_twice_stops_first(self):
        monitor = PingMonitor()
        with patch("subprocess.Popen") as mock_popen:

            def _make_mock_process():
                p = MagicMock()
                p.stdout = MagicMock()
                p.stdout.readline.return_value = (
                    "64 bytes from 10.99.80.160: icmp_seq=1 ttl=64 time=5.0 ms\n"
                )
                p.poll.return_value = None
                return p

            proc1 = _make_mock_process()
            proc2 = _make_mock_process()
            mock_popen.side_effect = [proc1, proc2]

            monitor.start(ALLOWLISTED_IP)
            first_process = monitor._process
            monitor.start(ALLOWLISTED_IP)
            proc1.terminate.assert_called()
            assert monitor._process is not first_process
            monitor.stop()


class TestPingMonitorParsingEdgeCases:
    """Edge cases for line parsing across platforms."""

    def test_extract_rtt_varying_whitespace(self):
        rtt = _extract_rtt(
            "64 bytes from 10.99.80.160: icmp_seq=5 ttl=64  time=0.567 ms"
        )
        assert rtt == 0.567

    def test_extract_rtt_windows_less_than_1ms(self):
        rtt = _extract_rtt(
            "Reply from 10.99.80.160: bytes=32 time<1ms TTL=64"
        )
        assert rtt == 1.0

    def test_extract_rtt_windows_statistics_ignored(self):
        assert _extract_rtt("Ping statistics for 10.99.80.160:") is None
        assert _extract_rtt(
            "    Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),"
        ) is None
