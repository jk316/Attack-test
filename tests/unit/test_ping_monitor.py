"""Tests for PingMonitor — continuous background ping monitoring."""
import sys
import time
from unittest.mock import patch, MagicMock, PropertyMock
import pytest

ALLOWLISTED_IP = "10.99.80.160"


class TestPingMonitorInit:
    """Tests for PingMonitor initialization and singleton."""

    def test_initial_state_not_running(self):
        """新建的 PingMonitor 不应该在运行中。"""
        from src.tools.ping_monitor import PingMonitor

        monitor = PingMonitor()
        assert monitor.is_running() is False
        assert monitor.target_ip is None

    def test_singleton_returns_same_instance(self):
        """get_ping_monitor() 应该返回同一个单例实例。"""
        from src.tools.ping_monitor import get_ping_monitor, PingMonitor

        m1 = get_ping_monitor()
        m2 = get_ping_monitor()
        assert m1 is m2
        assert isinstance(m1, PingMonitor)

    def test_start_stores_target_ip(self):
        """start() 应该存储目标 IP。"""
        from src.tools.ping_monitor import PingMonitor

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

    def test_linux_continuous_ping_cmd(self):
        """Linux 下应该构建持续 ping 命令。"""
        from src.tools.ping_monitor import PingMonitor

        with patch.object(sys, "platform", "linux"):
            monitor = PingMonitor()
            cmd = monitor._build_continuous_ping_cmd(ALLOWLISTED_IP, 1.0)
            assert cmd[0] in ("ping",)
            # Linux: ping with no -c means continuous
            assert "-c" not in cmd
            assert ALLOWLISTED_IP in cmd

    def test_windows_continuous_ping_cmd(self):
        """Windows 下应该构建 -t 持续 ping 命令。"""
        from src.tools.ping_monitor import PingMonitor

        with patch.object(sys, "platform", "win32"):
            monitor = PingMonitor()
            cmd = monitor._build_continuous_ping_cmd(ALLOWLISTED_IP, 1.0)
            # Windows: ping -t <ip> for continuous
            assert "-t" in cmd
            assert ALLOWLISTED_IP in cmd


class TestPingMonitorParsing:
    """Tests for ping output line parsing."""

    def test_parse_linux_reply(self):
        """解析 Linux ping 回复行。"""
        from src.tools.ping_monitor import PingMonitor

        monitor = PingMonitor()
        rtt = monitor._parse_line_rtt(
            "64 bytes from 10.99.80.160: icmp_seq=1 ttl=64 time=12.345 ms"
        )
        assert rtt == 12.345

    def test_parse_windows_reply(self):
        """解析 Windows ping 回复行。"""
        from src.tools.ping_monitor import PingMonitor

        monitor = PingMonitor()
        rtt = monitor._parse_line_rtt(
            "Reply from 10.99.80.160: bytes=32 time=8ms TTL=64"
        )
        assert rtt == 8.0

    def test_parse_timeout_line_returns_none(self):
        """超时行应该返回 None。"""
        from src.tools.ping_monitor import PingMonitor

        monitor = PingMonitor()
        assert monitor._parse_line_rtt("Request timed out.") is None
        assert monitor._parse_line_rtt("Request timeout for icmp_seq 1") is None

    def test_parse_summary_line_returns_none(self):
        """统计摘要行应该返回 None。"""
        from src.tools.ping_monitor import PingMonitor

        monitor = PingMonitor()
        assert monitor._parse_line_rtt(
            "--- 10.99.80.160 ping statistics ---"
        ) is None

    def test_parse_empty_line_returns_none(self):
        """空行应该返回 None。"""
        from src.tools.ping_monitor import PingMonitor

        monitor = PingMonitor()
        assert monitor._parse_line_rtt("") is None
        assert monitor._parse_line_rtt("   ") is None


class TestPingMonitorStats:
    """Tests for get_stats and get_samples_since."""

    def _make_monitor_with_samples(self, samples: list[tuple[float, float]]):
        """Helper: create a monitor with pre-loaded samples and a mock process."""
        from src.tools.ping_monitor import PingMonitor

        monitor = PingMonitor()
        monitor._running = True
        monitor._target_ip = ALLOWLISTED_IP
        # Mock the process so is_running() returns True
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # process still running
        monitor._process = mock_proc
        for ts, rtt in samples:
            monitor._rtt_samples.append((ts, rtt))
        return monitor

    def test_get_stats_returns_correct_average(self):
        """get_stats 应该返回正确的平均值。"""
        now = time.time()
        monitor = self._make_monitor_with_samples([
            (now - 3, 10.0),
            (now - 2, 20.0),
            (now - 1, 30.0),
        ])

        stats = monitor.get_stats(window_s=10)
        assert stats["avg_rtt_ms"] == 20.0
        assert stats["min_rtt_ms"] == 10.0
        assert stats["max_rtt_ms"] == 30.0
        assert stats["sample_count"] == 3
        assert stats["loss_pct"] == 0.0

    def test_get_stats_empty_returns_defaults(self):
        """没有样本时应该返回默认值。"""
        from src.tools.ping_monitor import PingMonitor

        monitor = PingMonitor()
        monitor._running = True
        monitor._target_ip = ALLOWLISTED_IP

        stats = monitor.get_stats(window_s=10)
        assert stats["sample_count"] == 0
        assert stats["loss_pct"] == 100.0

    def test_get_stats_respects_window(self):
        """get_stats 应该仅返回时间窗口内的样本。"""
        now = time.time()
        monitor = self._make_monitor_with_samples([
            (now - 10, 5.0),   # outside 5s window
            (now - 3, 10.0),   # inside
            (now - 1, 30.0),   # inside
        ])

        stats = monitor.get_stats(window_s=5)
        assert stats["sample_count"] == 2
        assert stats["avg_rtt_ms"] == 20.0

    def test_get_samples_since_returns_filtered(self):
        """get_samples_since 应该返回指定时间之后的样本。"""
        now = time.time()
        monitor = self._make_monitor_with_samples([
            (now - 10, 5.0),
            (now - 3, 10.0),
            (now - 1, 30.0),
        ])

        samples = monitor.get_samples_since(now - 5)
        assert len(samples) == 2
        assert samples[0]["rtt_ms"] == 10.0
        assert samples[1]["rtt_ms"] == 30.0

    def test_get_samples_since_empty_when_no_new_data(self):
        """没有新数据时 get_samples_since 返回空列表。"""
        now = time.time()
        monitor = self._make_monitor_with_samples([
            (now - 10, 5.0),
        ])

        # now-10 is 10s ago, which is before the cutoff of now-1
        samples = monitor.get_samples_since(now - 1)
        assert len(samples) == 0

    def test_get_samples_since_all_after_cutoff(self):
        """get_samples_since 使用严格 > 比较。"""
        from src.tools.ping_monitor import PingMonitor

        monitor = PingMonitor()
        monitor._running = True
        monitor._target_ip = ALLOWLISTED_IP
        t0 = time.time()
        monitor._rtt_samples.append((t0 - 0.01, 5.0))
        monitor._rtt_samples.append((t0, 10.0))
        monitor._rtt_samples.append((t0 + 0.01, 15.0))

        samples = monitor.get_samples_since(t0)
        # Only samples with timestamp > t0
        assert len(samples) == 1
        assert samples[0]["rtt_ms"] == 15.0

    def test_get_stats_not_running_returns_empty(self):
        """未运行时 get_stats 返回空统计。"""
        from src.tools.ping_monitor import PingMonitor

        monitor = PingMonitor()
        stats = monitor.get_stats(window_s=5)
        assert stats["sample_count"] == 0
        assert stats["monitor_active"] is False


class TestPingMonitorStop:
    """Tests for stop and cleanup."""

    def test_stop_kills_process(self):
        """stop 应该终止子进程。"""
        from src.tools.ping_monitor import PingMonitor

        monitor = PingMonitor()
        with patch("subprocess.Popen") as mock_popen:
            mock_process = MagicMock()
            mock_process.stdout = MagicMock()
            mock_process.stdout.readline.side_effect = ["", Exception("stop")]
            mock_process.poll.return_value = None  # still running
            mock_popen.return_value = mock_process

            monitor.start(ALLOWLISTED_IP)
            monitor.stop()

            mock_process.terminate.assert_called()
            assert monitor.is_running() is False
            assert monitor.target_ip is None

    def test_stop_when_not_running_is_safe(self):
        """未运行时调用 stop 应该是安全的。"""
        from src.tools.ping_monitor import PingMonitor

        monitor = PingMonitor()
        monitor.stop()  # should not raise
        assert monitor.is_running() is False

    def test_start_twice_stops_first(self):
        """重复 start 应该先停止旧的再启动新的。"""
        from src.tools.ping_monitor import PingMonitor

        monitor = PingMonitor()
        with patch("subprocess.Popen") as mock_popen:

            def _make_mock_process():
                p = MagicMock()
                p.stdout = MagicMock()
                # Return valid ping replies so reader thread stays alive
                p.stdout.readline.return_value = "64 bytes from 10.99.80.160: icmp_seq=1 ttl=64 time=5.0 ms\n"
                p.poll.return_value = None
                return p

            proc1 = _make_mock_process()
            proc2 = _make_mock_process()
            mock_popen.side_effect = [proc1, proc2]

            monitor.start(ALLOWLISTED_IP)
            first_process = monitor._process
            monitor.start(ALLOWLISTED_IP)
            # The old process should have been terminated
            proc1.terminate.assert_called()
            assert monitor._process is not first_process
            monitor.stop()


class TestPingMonitorParsingEdgeCases:
    """Edge cases for line parsing across platforms."""

    def test_parse_linux_reply_with_varying_whitespace(self):
        """Linux 回复行有变化空格。"""
        from src.tools.ping_monitor import PingMonitor

        monitor = PingMonitor()
        # Double spaces in some places
        rtt = monitor._parse_line_rtt(
            "64 bytes from 10.99.80.160: icmp_seq=5 ttl=64  time=0.567 ms"
        )
        assert rtt == 0.567

    def test_parse_windows_reply_with_ttl_first(self):
        """Windows 回复格式：Reply from ...: bytes=32 time<1ms TTL=64。"""
        from src.tools.ping_monitor import PingMonitor

        monitor = PingMonitor()
        rtt = monitor._parse_line_rtt(
            "Reply from 10.99.80.160: bytes=32 time<1ms TTL=64"
        )
        assert rtt == 1.0

    def test_parse_windows_ping_statistics_line(self):
        """Windows ping statistics 行应该被忽略。"""
        from src.tools.ping_monitor import PingMonitor

        monitor = PingMonitor()
        assert monitor._parse_line_rtt("Ping statistics for 10.99.80.160:") is None
        assert monitor._parse_line_rtt(
            "    Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),"
        ) is None
