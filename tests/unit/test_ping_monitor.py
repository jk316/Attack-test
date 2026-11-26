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
        assert sample.rtt_ms is None  # all-lost → no RTT, not misleading 0.0
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

    def test_get_stats_weighted_avg(self):
        """fping_q 周期汇总的 avg_rtt 应按 received 加权。"""
        now = time.time()
        # Cycle 1: 9 received, avg=10ms → weighted contribution 90
        # Cycle 2: 1 received, avg=100ms → weighted contribution 100
        # True weighted avg = 190/10 = 19ms (vs unweighted 55ms)
        monitor = self._make_monitor_with_samples([
            MonitorSample(ts=now - 2, rtt_ms=10.0, sent=10, received=9),
            MonitorSample(ts=now - 1, rtt_ms=100.0, sent=10, received=1),
        ])

        stats = monitor.get_stats(window_s=10)
        assert stats["avg_rtt_ms"] == 19.0


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


class TestConfigDrivenBuild:
    """T005：配置读取与换算（G-001/G-002，research 决策 2/3）。

    env PING_MONITOR_* → _build_fping_q_cmd / start / get_stats / deque 上限。
    """

    def test_fping_q_period_from_probes_per_sec(self, monkeypatch):
        from src.tools.ping_monitor import PingMonitor

        monkeypatch.setenv("PING_MONITOR_PROBES_PER_SEC", "10")
        monkeypatch.setenv("PING_MONITOR_SUMMARY_INTERVAL_S", "1")
        assert PingMonitor._build_fping_q_cmd("10.99.80.160") == [
            "fping", "-l", "-Q", "1", "-p", "100", "10.99.80.160",
        ]

    def test_fping_q_summary_interval_from_env(self, monkeypatch):
        from src.tools.ping_monitor import PingMonitor

        monkeypatch.setenv("PING_MONITOR_PROBES_PER_SEC", "5")
        monkeypatch.setenv("PING_MONITOR_SUMMARY_INTERVAL_S", "2")
        cmd = PingMonitor._build_fping_q_cmd("10.99.80.160")
        assert cmd[3] == "2"       # -Q 摘要间隔
        assert cmd[5] == "200"     # -p 周期 = 1000/5 ms

    def test_probes_frequency_floor_0_1s(self, monkeypatch):
        """频率下限 0.1 s：probes_per_sec>10 被钳制（周期 ≥100ms）。"""
        from src.tools.ping_monitor import PingMonitor

        monkeypatch.setenv("PING_MONITOR_PROBES_PER_SEC", "100")
        cmd = PingMonitor._build_fping_q_cmd("10.99.80.160")
        assert int(cmd[5]) >= 100  # -p 钳到 ≥100ms

    def test_nonpositive_probes_rejected(self, monkeypatch):
        from src.tools.ping_monitor import PingMonitor

        monkeypatch.setenv("PING_MONITOR_PROBES_PER_SEC", "0")
        with pytest.raises(ValueError, match="probes_per_sec"):
            PingMonitor._build_fping_q_cmd("10.99.80.160")

    def test_env_missing_falls_back_to_defaults(self, monkeypatch):
        from src.tools.ping_monitor import PingMonitor

        for var in ("PING_MONITOR_PROBES_PER_SEC", "PING_MONITOR_SUMMARY_INTERVAL_S"):
            monkeypatch.delenv(var, raising=False)
        assert PingMonitor._build_fping_q_cmd("10.99.80.160") == [
            "fping", "-l", "-Q", "1", "-p", "100", "10.99.80.160",
        ]

    def test_fallback_interval_used_by_start(self, monkeypatch):
        from src.tools.ping_monitor import PingMonitor, _fping_available

        monkeypatch.setenv("PING_MONITOR_FALLBACK_INTERVAL_S", "2.5")
        captured = {}

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            return None  # start() 会失败——但 cmd 已被捕获

        with patch("src.tools.ping_monitor._fping_available", return_value=False), \
             patch("src.tools.ping_monitor.subprocess.Popen", side_effect=fake_popen):
            try:
                PingMonitor().start("10.99.80.160")  # interval_s 缺省 → env
            except (AttributeError, RuntimeError):
                pass  # fake Popen 返回 None 导致后续失败，命令已捕获
        if sys.platform == "win32":
            # Windows 用 ping -t -w <timeout_ms>（interval_s*1000）
            assert captured["cmd"][captured["cmd"].index("-w") + 1] == "2500"
        else:
            assert captured["cmd"][captured["cmd"].index("-i") + 1] == "2.5"

    def test_deque_maxlen_from_env(self, monkeypatch):
        from src.tools.ping_monitor import PingMonitor

        monkeypatch.setenv("PING_MONITOR_MAX_SAMPLES", "100")
        assert PingMonitor()._samples.maxlen == 100

    def test_deque_default_maxlen(self, monkeypatch):
        from src.tools.ping_monitor import PingMonitor

        monkeypatch.delenv("PING_MONITOR_MAX_SAMPLES", raising=False)
        assert PingMonitor()._samples.maxlen == 4000

    def test_stats_window_default_from_env(self, monkeypatch):
        from src.tools.ping_monitor import PingMonitor

        monkeypatch.setenv("PING_MONITOR_STATS_WINDOW_S", "2.0")
        m = PingMonitor()
        result = m.get_stats()  # 未运行 + window 缺省 → env
        assert result["window_s"] == 2.0

    def test_stats_window_default_fallback(self, monkeypatch):
        from src.tools.ping_monitor import PingMonitor

        monkeypatch.delenv("PING_MONITOR_STATS_WINDOW_S", raising=False)
        m = PingMonitor()
        assert m.get_stats()["window_s"] == 5.0


class TestFpingQSummaryParsing:
    """T007：fping -Q 摘要行/超时行/非摘要行解析（对照 contracts/monitor-sample.md）。"""

    def test_summary_line_weighted_counts_and_avg(self):
        from src.tools.ping_monitor import PingMonitor

        line = "10.99.80.160 : xmt/rcv/%loss = 10/8/20%, min/avg/max = 2.1/5.7/12.3"
        sample = PingMonitor._parse_fping_summary_line(line)
        assert sample is not None
        assert sample.sent == 10
        assert sample.received == 8
        assert sample.rtt_ms == 5.7  # avg

    def test_all_lost_summary_has_null_rtt(self):
        from src.tools.ping_monitor import PingMonitor

        line = "10.99.80.160 : xmt/rcv/%loss = 10/0/100%, min/avg/max = 0/0/0"
        sample = PingMonitor._parse_fping_summary_line(line)
        assert sample is not None
        assert sample.sent == 10
        assert sample.received == 0
        assert sample.rtt_ms is None  # 全丢不得记为 0 ms

    def test_timeout_line_not_a_summary(self):
        from src.tools.ping_monitor import PingMonitor

        # fping 超时行（非 -Q 摘要行）不产生样本
        line = "10.99.80.160 : [1], 84 bytes, timeout (2.12 avg, 50% loss)"
        assert PingMonitor._parse_fping_summary_line(line) is None

    def test_icmp_header_and_blank_not_samples(self):
        from src.tools.ping_monitor import PingMonitor

        assert PingMonitor._parse_fping_summary_line(
            "ICMP Host Unreachable from 192.168.1.1 for ICMP Echo sent to 10.99.80.160") is None
        assert PingMonitor._parse_fping_summary_line("") is None
        assert PingMonitor._parse_fping_summary_line("   ") is None


class TestCrossLanguageLoss:
    """T008：跨语言丢包解析（G-004）。"""

    def test_english_request_timed_out(self):
        from src.tools.ping_monitor import PingMonitor

        s = PingMonitor._parse_ping_line("Request timed out.")
        assert s is not None and s.sent == 1 and s.received == 0 and s.rtt_ms is None

    def test_english_destination_unreachable(self):
        from src.tools.ping_monitor import PingMonitor

        s = PingMonitor._parse_ping_line(
            "Reply from 192.168.1.1: Destination host unreachable.")
        assert s is not None and s.sent == 1 and s.received == 0 and s.rtt_ms is None

    def test_chinese_request_timeout(self):
        from src.tools.ping_monitor import PingMonitor

        s = PingMonitor._parse_ping_line("请求超时。")
        assert s is not None and s.sent == 1 and s.received == 0 and s.rtt_ms is None

    def test_chinese_unreachable(self):
        """中文不可达模式「无法访问目标主机」（G-004 缺口）。"""
        from src.tools.ping_monitor import PingMonitor

        s = PingMonitor._parse_ping_line("无法访问目标主机。")
        assert s is not None and s.sent == 1 and s.received == 0 and s.rtt_ms is None

    def test_unix_reply_rtt(self):
        from src.tools.ping_monitor import PingMonitor

        s = PingMonitor._parse_ping_line(
            "64 bytes from 10.99.80.160: icmp_seq=0 ttl=64 time=12.34 ms")
        assert s is not None and s.rtt_ms == 12.34 and s.received == 1

    def test_windows_reply_rtt(self):
        from src.tools.ping_monitor import PingMonitor

        s = PingMonitor._parse_ping_line(
            "Reply from 10.99.80.160: bytes=32 time=5ms TTL=64")
        assert s is not None and s.rtt_ms == 5.0 and s.received == 1


class TestWeightedStats:
    """T009：加权统计口径（G-005，对照 contracts/monitor-sample.md §2/§4）。"""

    def _monitor(self):
        from src.tools.ping_monitor import PingMonitor, MonitorSample

        now = time.time()
        m = TestPingMonitorStats._make_monitor_with_samples(self, [
            MonitorSample(ts=now - 3, rtt_ms=5.0, sent=10, received=8),
            MonitorSample(ts=now - 2, rtt_ms=20.0, sent=1, received=1),
        ])
        return m, now

    def test_loss_formula_one_minus_received_over_sent(self):
        m, _ = self._monitor()
        stats = m.get_stats(window_s=10)
        # sent=11, received=9 → (1 - 9/11) * 100 = 18.2
        assert stats["loss_pct"] == round((1 - 9 / 11) * 100, 1)
        assert stats["sample_count"] == 9
        assert stats["sent_count"] == 11

    def test_weighted_avg_matches_manual(self):
        m, _ = self._monitor()
        stats = m.get_stats(window_s=10)
        # (5.0*8 + 20.0*1) / 9 = 6.667
        assert stats["avg_rtt_ms"] == round((5.0 * 8 + 20.0 * 1) / 9, 3)

    def test_not_running_returns_inactive_zero_counts(self):
        from src.tools.ping_monitor import PingMonitor

        stats = PingMonitor().get_stats(window_s=5)
        assert stats["monitor_active"] is False
        assert stats["sample_count"] == 0
        assert stats["sent_count"] == 0
        assert stats["loss_pct"] == 100.0


class TestConcurrentQueries:
    """T010：并发一致性（SC-004）。"""

    def test_concurrent_queries_no_exception_and_consistent(self):
        import threading

        from src.tools.ping_monitor import PingMonitor, MonitorSample

        now = time.time()
        m = TestPingMonitorStats._make_monitor_with_samples(self, [
            MonitorSample(ts=now - 2, rtt_ms=10.0, sent=10, received=10),
            MonitorSample(ts=now - 1, rtt_ms=20.0, sent=10, received=10),
        ])

        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(100):
                    stats = m.get_stats(window_s=10)
                    assert stats["sent_count"] == 20
                    samples = m.get_samples_since(now - 3)
                    assert len(samples) == 2
            except Exception as e:  # pragma: no cover - 收集异常
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert errors == []
        # 串行对照：样本数与串行一致
        assert len(m.get_samples_since(now - 3)) == 2
        assert m.get_stats(window_s=10)["sample_count"] == 20
