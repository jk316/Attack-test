"""Integration tests for ping monitor subprocess lifecycle (T011 / SC-006).

真实命令构造 + 真实进程生命周期，但**零网络 I/O**（安全红线）：subprocess.Popen
被包装——先断言命令构造正确（真实 _build_fping_q_cmd / _build_ping_cmd 输出），
再以 `sleep` 子进程代替 ping 二进制，避免向真实目标发送 ICMP。连续 20 次
start/stop 后所有子进程已退出、读线程已回收，系统无残留探测进程。
"""
import subprocess
import time
from unittest.mock import patch

import pytest

ALLOWLISTED_IP = "10.99.80.160"


class _SpawnRecorder:
    """Popen 包装：记录命令并用 sleep 子进程模拟 ping 生命周期。"""

    def __init__(self):
        self.spawned: list[subprocess.Popen] = []
        self.commands: list[list[str]] = []
        self._real_popen = subprocess.Popen

    def __call__(self, cmd, **kwargs):
        self.commands.append(list(cmd))
        assert cmd[0] in ("fping", "ping"), f"意外命令: {cmd}"
        proc = self._real_popen(["sleep", "30"], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.spawned.append(proc)
        return proc


class TestPingMonitorLifecycle:
    def test_fping_q_command_construction(self, monkeypatch):
        from src.tools.ping_monitor import PingMonitor

        monkeypatch.setenv("PING_MONITOR_PROBES_PER_SEC", "10")
        monkeypatch.setenv("PING_MONITOR_SUMMARY_INTERVAL_S", "1")
        cmd = PingMonitor._build_fping_q_cmd(ALLOWLISTED_IP)
        assert cmd == ["fping", "-l", "-Q", "1", "-p", "100", ALLOWLISTED_IP]

    def test_fallback_ping_command_construction(self):
        from src.tools.ping_monitor import PingMonitor

        cmd = PingMonitor._build_ping_cmd(ALLOWLISTED_IP, 1.0)
        assert cmd[0] == "ping"
        assert "-i" in cmd and "1.0" in cmd
        assert ALLOWLISTED_IP == cmd[-1]

    def test_twenty_start_stop_no_orphan_processes(self, monkeypatch):
        from src.tools.ping_monitor import PingMonitor

        recorder = _SpawnRecorder()
        monkeypatch.setattr("src.tools.ping_monitor._fping_available",
                            lambda: False)  # 走系统 ping 回退路径
        with patch("src.tools.ping_monitor.subprocess.Popen",
                   side_effect=recorder):
            for _ in range(20):
                m = PingMonitor()
                m.start(ALLOWLISTED_IP, interval_s=1.0)
                assert m.is_running()
                m.stop()
                assert not m.is_running()

        # 所有 spawn 的子进程都已退出（无孤儿探测进程）
        deadline = time.time() + 5
        while time.time() < deadline and any(p.poll() is None
                                              for p in recorder.spawned):
            time.sleep(0.05)
        assert all(p.poll() is not None for p in recorder.spawned)
        assert len(recorder.spawned) == 20
        # 20 次启动的命令构造均正确
        assert all(cmd[0] == "ping" and ALLOWLISTED_IP == cmd[-1]
                   for cmd in recorder.commands)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
