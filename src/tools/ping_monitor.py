"""Continuous background ping monitor for real-time RTT observation.

Provides a thread-safe singleton PingMonitor that runs ping in a subprocess
and parses output line-by-line, storing (timestamp, rtt_ms) samples.
"""

import re
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Optional

from src.tools.ping_rtt_tool import validate_target


# ── Per-line RTT pattern (handles both Unix and Windows) ──────────
# Unix: 64 bytes from 1.2.3.4: icmp_seq=1 ttl=64 time=12.345 ms
_UNIX_RTT_RE = re.compile(r"time[<=](\d+\.?\d*)\s*ms", re.IGNORECASE)
# Windows: Reply from 1.2.3.4: bytes=32 time=8ms TTL=64
_WIN_RTT_RE = re.compile(r"time[<=](\d+\.?\d*)\s*ms", re.IGNORECASE)

# Lines definitely not containing RTT data
_NON_RTT_PATTERNS = [
    re.compile(r"^PING\s", re.IGNORECASE),
    re.compile(r"^Pinging\s", re.IGNORECASE),
    re.compile(r"ping statistics", re.IGNORECASE),
    re.compile(r"^\s*$"),
    re.compile(r"^\-\-\-"),
    re.compile(r"Packets:", re.IGNORECASE),
    re.compile(r"Approximate round trip", re.IGNORECASE),
    re.compile(r"round-trip", re.IGNORECASE),
    re.compile(r"^\s*Reply from.*:.*destination", re.IGNORECASE),  # "Reply from X: Destination host unreachable"
    re.compile(r"^\s*Reply from.*:.*TTL expired", re.IGNORECASE),
]


class PingMonitor:
    """Background ping subprocess that continuously measures RTT.

    Runs a platform-appropriate ``ping`` command in a subprocess, parses
    reply lines in a daemon thread, and stores (timestamp, rtt_ms) samples
    in a thread-safe deque for querying by tool functions.

    Typical usage::

        monitor = PingMonitor()
        monitor.start("10.99.80.160", interval_s=1.0)

        # ... later, while traffic is being sent ...
        stats = monitor.get_stats(window_s=5.0)

        monitor.stop()
    """

    _MAX_SAMPLES = 2000

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None  # type: ignore[type-arg]
        self._reader_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._rtt_samples: deque[tuple[float, float]] = deque(maxlen=self._MAX_SAMPLES)
        self._running = False
        self._target_ip: Optional[str] = None
        self._stop_event = threading.Event()

    # ── Public API ─────────────────────────────────────────────────

    @property
    def target_ip(self) -> Optional[str]:
        """The IP address currently being pinged, or None."""
        return self._target_ip

    def is_running(self) -> bool:
        """Return True if the background ping subprocess is active."""
        return self._running and self._process is not None and self._process.poll() is None

    def start(self, ip: str, interval_s: float = 1.0) -> None:
        """Start continuous ping to *ip*.

        If a previous monitor was running it is stopped first.
        *interval_s* controls the per-ping interval on Linux; Windows
        ``ping -t`` sends as fast as the OS allows and ignores this.
        """
        validate_target(ip)

        if self.is_running():
            self.stop()

        self._target_ip = ip
        self._stop_event.clear()

        cmd = self._build_continuous_ping_cmd(ip, interval_s)
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,  # line-buffered
            )
        except FileNotFoundError:
            self._target_ip = None
            raise RuntimeError("ping command not found on this system")

        self._running = True
        self._reader_thread = threading.Thread(
            target=self._read_output,
            name="ping-monitor-reader",
            daemon=True,
        )
        self._reader_thread.start()

    def stop(self) -> None:
        """Stop the background ping subprocess and reader thread."""
        self._running = False
        self._stop_event.set()

        proc = self._process
        if proc is not None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
            except (ProcessLookupError, OSError):
                pass
            self._process = None

        # Wait briefly for reader thread to finish
        reader = self._reader_thread
        if reader is not None and reader.is_alive():
            reader.join(timeout=2)
        self._reader_thread = None
        self._target_ip = None

    def get_stats(self, window_s: float = 5.0) -> dict:
        """Return aggregate RTT stats for the last *window_s* seconds.

        Returns a dict suitable for the agent to consume::

            {
                "monitor_active": bool,
                "target_ip": str | null,
                "latest_rtt_ms": float | null,
                "avg_rtt_ms": float,
                "min_rtt_ms": float,
                "max_rtt_ms": float,
                "sample_count": int,
                "loss_pct": float,
                "window_s": float,
            }
        """
        if not self.is_running():
            return {
                "monitor_active": False,
                "target_ip": self._target_ip,
                "latest_rtt_ms": None,
                "avg_rtt_ms": 0.0,
                "min_rtt_ms": 0.0,
                "max_rtt_ms": 0.0,
                "sample_count": 0,
                "loss_pct": 100.0,
                "window_s": window_s,
            }

        cutoff = time.time() - window_s
        rtt_values: list[float] = []
        latest: Optional[float] = None

        with self._lock:
            for ts, rtt in self._rtt_samples:
                if ts >= cutoff:
                    rtt_values.append(rtt)
            if self._rtt_samples:
                latest = self._rtt_samples[-1][1]

        if not rtt_values:
            return {
                "monitor_active": True,
                "target_ip": self._target_ip,
                "latest_rtt_ms": latest,
                "avg_rtt_ms": latest if latest is not None else 0.0,
                "min_rtt_ms": latest if latest is not None else 0.0,
                "max_rtt_ms": latest if latest is not None else 0.0,
                "sample_count": 0,
                "loss_pct": 100.0 if latest is None else 0.0,
                "window_s": window_s,
            }

        return {
            "monitor_active": True,
            "target_ip": self._target_ip,
            "latest_rtt_ms": latest,
            "avg_rtt_ms": round(sum(rtt_values) / len(rtt_values), 3),
            "min_rtt_ms": round(min(rtt_values), 3),
            "max_rtt_ms": round(max(rtt_values), 3),
            "sample_count": len(rtt_values),
            "loss_pct": 0.0,  # RTT samples are only stored for successful replies
            "window_s": window_s,
        }

    def get_samples_since(self, timestamp: float) -> list[dict]:
        """Return all RTT samples with ``ts > timestamp``.

        Each sample is ``{"ts": float, "rtt_ms": float}``.
        Returns newest-first ordering.
        """
        result: list[dict] = []
        with self._lock:
            for ts, rtt in self._rtt_samples:
                if ts > timestamp:
                    result.append({"ts": round(ts, 3), "rtt_ms": rtt})
        return result

    # ── Internal helpers ───────────────────────────────────────────

    def _build_continuous_ping_cmd(self, ip: str, interval_s: float) -> list[str]:
        """Build platform-appropriate continuous ping command."""
        if sys.platform == "win32":
            # -t = continuous, -w = timeout per reply in ms
            timeout_ms = max(int(interval_s * 1000), 100)
            return ["ping", "-t", "-w", str(timeout_ms), ip]
        else:
            # Linux/macOS: omit -c for continuous, -i sets interval
            cmd = ["ping", "-i", str(max(interval_s, 0.2)), ip]
            # -W sets per-reply timeout in seconds
            cmd.insert(1, "-W")
            cmd.insert(2, str(max(int(interval_s) + 2, 3)))
            return cmd

    @staticmethod
    def _parse_line_rtt(line: str) -> Optional[float]:
        """Extract RTT value (in ms) from a single ping output line.

        Returns ``None`` if the line does not contain a valid RTT.
        """
        stripped = line.strip()
        if not stripped:
            return None

        for pat in _NON_RTT_PATTERNS:
            if pat.search(stripped):
                return None

        # Also skip "Reply from X: Destination ..." style unreachable lines
        if "unreachable" in stripped.lower():
            return None
        if "ttl expired" in stripped.lower():
            return None

        m = _UNIX_RTT_RE.search(stripped)
        if m:
            return float(m.group(1))

        return None

    def _read_output(self) -> None:
        """Read stdout from the ping subprocess in a loop (runs in daemon thread)."""
        proc = self._process
        if proc is None or proc.stdout is None:
            return

        try:
            while self._running and not self._stop_event.is_set():
                line = proc.stdout.readline()
                if not line:
                    # EOF — process exited
                    break
                rtt = self._parse_line_rtt(line)
                now = time.time()
                if rtt is not None:
                    with self._lock:
                        self._rtt_samples.append((now, rtt))
        except (ValueError, OSError):
            pass
        finally:
            self._running = False


# ── Module-level singleton ────────────────────────────────────────

_monitor: Optional[PingMonitor] = None
_monitor_lock = threading.Lock()


def get_ping_monitor() -> PingMonitor:
    """Return the module-level PingMonitor singleton, creating it if needed."""
    global _monitor
    if _monitor is None:
        with _monitor_lock:
            if _monitor is None:
                _monitor = PingMonitor()
    return _monitor
