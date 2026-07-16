"""Continuous background ping monitor for real-time RTT + loss observation.

Provides a thread-safe singleton PingMonitor that runs a ping subprocess
and parses output, storing per-probe ``MonitorSample`` entries.

Two backends, auto-selected at ``start()``:

* **fping** (preferred on non-Windows) — ``fping -l -p <ms>`` outputs one
  line per probe with running cumulative RTT and loss%::

      IP : [0], 84 bytes, 2.12 ms (2.12 avg, 0% loss)

* **system ping** (fallback) — the existing per-packet parser augmented with
  timeout/unreachable detection so ``loss_pct`` is computed from sent vs
  received counts instead of being hard-coded to 0.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

from src.tools.ping_rtt_tool import validate_target

# ── Per-line RTT pattern (system ping, handles Unix and Windows) ────
_UNIX_RTT_RE = re.compile(r"time[<=](\d+\.?\d*)\s*ms", re.IGNORECASE)
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
    re.compile(r"^\s*Reply from.*:.*destination", re.IGNORECASE),
    re.compile(r"^\s*Reply from.*:.*TTL expired", re.IGNORECASE),
]

# ── Lines that indicate a lost ping probe ───────────────────────────
_LOSS_PATTERNS = [
    re.compile(r"Request\s+timed\s+out", re.IGNORECASE),
    re.compile(r"Destination\s+host\s+unreachable", re.IGNORECASE),
    re.compile(r"请求超时"),  # Windows Chinese locale
]

# ── fping output parsing ────────────────────────────────────────────
# Example (success):  "10.99.80.160 : [0], 84 bytes, 2.12 ms (2.12 avg, 0% loss)"
# Example (timeout):  "10.99.80.160 : [1], 84 bytes, timeout (2.12 avg, 50% loss)"
# Example (unreachable, rare): "ICMP Host Unreachable from 192.168.1.1 ..."

_FPING_SUCCESS_RE = re.compile(
    r"\s+([\d.]+)\s*ms\s*\(([\d.]+)\s*avg,\s*(\d+)%\s*loss\)"
)
_FPING_TIMEOUT_RE = re.compile(
    r"timeout\s*\(([\d.]+)\s*avg,\s*(\d+)%\s*loss\)"
)


# ── Data model ──────────────────────────────────────────────────────


@dataclass
class MonitorSample:
    """A single ping probe result.

    Stored in a thread-safe deque and aggregated by ``get_stats()`` /
    ``get_samples_since()``.  ``sent`` / ``received`` are always 0 or 1
    per sample; loss_pct is computed from their sums in the aggregation
    methods, NOT stored per-sample.
    """

    ts: float          # time.time() when the line was parsed
    rtt_ms: Optional[float]  # RTT in ms, or None when the probe was lost
    sent: int = 1
    received: int = 1        # 0 for lost probes


# ── PingMonitor ─────────────────────────────────────────────────────


class PingMonitor:
    """Background ping subprocess that continuously measures RTT + loss.

    Runs a platform-appropriate ping / fping command in a subprocess,
    parses output in a daemon thread, and stores ``MonitorSample``
    entries in a thread-safe deque for querying by tool functions.

    Typical usage::

        monitor = PingMonitor()
        monitor.start("10.99.80.160", interval_s=1.0)

        # ... later, while traffic is being sent ...
        stats = monitor.get_stats(window_s=5.0)

        monitor.stop()
    """

    _MAX_SAMPLES = 4000  # doubled from 2000 — loss + RTT samples share one deque

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None  # type: ignore[type-arg]
        self._reader_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._samples: deque[MonitorSample] = deque(maxlen=self._MAX_SAMPLES)
        self._running = False
        self._target_ip: Optional[str] = None
        self._stop_event = threading.Event()
        self._backend: str = ""  # "fping" | "ping"

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
        *interval_s* controls the per-ping interval (fping and Linux native);
        Windows ``ping -t`` ignores it.
        """
        validate_target(ip)

        if self.is_running():
            self.stop()

        self._target_ip = ip
        self._stop_event.clear()

        # Auto-select backend
        if sys.platform != "win32" and _fping_available():
            self._backend = "fping"
            cmd = self._build_fping_cmd(ip, interval_s)
            parser: Callable[[str], Optional[MonitorSample]] = self._parse_fping_line
        else:
            self._backend = "ping"
            cmd = self._build_ping_cmd(ip, interval_s)
            parser = self._parse_ping_line

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            self._target_ip = None
            raise RuntimeError(f"ping binary not found on this system (backend={self._backend})")

        self._running = True
        self._reader_thread = threading.Thread(
            target=self._read_output,
            args=(parser,),
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

        reader = self._reader_thread
        if reader is not None and reader.is_alive():
            reader.join(timeout=2)
        self._reader_thread = None
        self._target_ip = None

    def get_stats(self, window_s: float = 5.0) -> dict:
        """Return aggregate RTT + loss stats for the last *window_s* seconds.

        Returns a dict suitable for the agent to consume::

            {
                "monitor_active": bool,
                "target_ip": str | null,
                "latest_rtt_ms": float | null,
                "avg_rtt_ms": float,
                "min_rtt_ms": float,
                "max_rtt_ms": float,
                "sample_count": int,      # received probes
                "sent_count": int,        # all probes sent in window
                "loss_pct": float,        # real loss percentage (NEW)
                "window_s": float,
                "backend": str,           # "fping" | "ping"
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
                "sent_count": 0,
                "loss_pct": 100.0,
                "window_s": window_s,
                "backend": self._backend,
            }

        cutoff = time.time() - window_s
        rtt_values: list[float] = []
        total_sent = 0
        total_received = 0
        latest: Optional[float] = None

        with self._lock:
            for s in self._samples:
                if s.ts >= cutoff:
                    total_sent += s.sent
                    total_received += s.received
                    if s.received > 0 and s.rtt_ms is not None:
                        rtt_values.append(s.rtt_ms)
            if self._samples:
                latest = self._samples[-1].rtt_ms

        if not rtt_values:
            loss_pct = 100.0 if total_sent > 0 else 0.0
            return {
                "monitor_active": True,
                "target_ip": self._target_ip,
                "latest_rtt_ms": latest,
                "avg_rtt_ms": latest if latest is not None else 0.0,
                "min_rtt_ms": latest if latest is not None else 0.0,
                "max_rtt_ms": latest if latest is not None else 0.0,
                "sample_count": total_received,
                "sent_count": total_sent,
                "loss_pct": loss_pct,
                "window_s": window_s,
                "backend": self._backend,
            }

        loss_pct = round((1 - total_received / total_sent) * 100, 1) if total_sent > 0 else 0.0

        return {
            "monitor_active": True,
            "target_ip": self._target_ip,
            "latest_rtt_ms": latest,
            "avg_rtt_ms": round(sum(rtt_values) / len(rtt_values), 3),
            "min_rtt_ms": round(min(rtt_values), 3),
            "max_rtt_ms": round(max(rtt_values), 3),
            "sample_count": total_received,
            "sent_count": total_sent,
            "loss_pct": loss_pct,
            "window_s": window_s,
            "backend": self._backend,
        }

    def get_samples_since(self, timestamp: float) -> list[dict]:
        """Return all probe results with ``ts > timestamp``.

        Each sample is ``{"ts": float, "rtt_ms": float | None, "sent": int,
        "received": int}``.  ``rtt_ms`` may be ``None`` for lost probes.

        Returns oldest-first ordering.
        """
        result: list[dict] = []
        with self._lock:
            for s in self._samples:
                if s.ts > timestamp:
                    result.append({
                        "ts": round(s.ts, 3),
                        "rtt_ms": s.rtt_ms,
                        "sent": s.sent,
                        "received": s.received,
                    })
        return result

    # ── Backend: system ping ────────────────────────────────────────

    @staticmethod
    def _build_ping_cmd(ip: str, interval_s: float) -> list[str]:
        """Build platform-appropriate continuous ping command."""
        if sys.platform == "win32":
            timeout_ms = max(int(interval_s * 1000), 100)
            return ["ping", "-t", "-w", str(timeout_ms), ip]
        else:
            cmd = ["ping", "-i", str(max(interval_s, 0.2)), ip]
            cmd.insert(1, "-W")
            cmd.insert(2, str(max(int(interval_s) + 2, 3)))
            return cmd

    @staticmethod
    def _parse_ping_line(line: str) -> Optional[MonitorSample]:
        """Parse a single system-ping output line into a MonitorSample.

        Returns:
            ``MonitorSample`` for replies and detected loss lines;
            ``None`` for non-probe lines (headers, summaries, blanks).
        """
        now = time.time()

        # Try RTT extraction first (successful reply)
        rtt = _extract_rtt(line)
        if rtt is not None:
            return MonitorSample(ts=now, rtt_ms=rtt, sent=1, received=1)

        # Detect loss lines (timeout / unreachable)
        if _is_loss_line(line):
            return MonitorSample(ts=now, rtt_ms=None, sent=1, received=0)

        return None

    # ── Backend: fping ──────────────────────────────────────────────

    @staticmethod
    def _build_fping_cmd(ip: str, interval_s: float) -> list[str]:
        """Build fping loop command.

        ``-l``: loop mode (continuous until killed)
        ``-p <ms>``: period between pings in milliseconds
        ``-t <ms>``: per-probe timeout
        """
        interval_ms = max(int(interval_s * 1000), 100)
        timeout_ms = max(interval_ms + 2000, 3000)
        return ["fping", "-l", "-p", str(interval_ms), "-t", str(timeout_ms), ip]

    @staticmethod
    def _parse_fping_line(line: str) -> Optional[MonitorSample]:
        """Parse an fping output line into a MonitorSample.

        fping ``-l`` outputs one line per probe::

            IP : [seq], N bytes, RTT ms (avg avg, loss% loss)
            IP : [seq], N bytes, timeout (avg avg, loss% loss)

        Returns ``None`` for non-probe lines.
        """
        now = time.time()
        stripped = line.strip()
        if not stripped:
            return None

        # Skip non-probe fping lines (ICMP Host Unreachable headers, etc.)
        if stripped.startswith("ICMP "):
            return None

        # Successful reply: "X.XX ms (avg avg, loss% loss)"
        m = _FPING_SUCCESS_RE.search(stripped)
        if m:
            return MonitorSample(ts=now, rtt_ms=float(m.group(1)), sent=1, received=1)

        # Timeout: "timeout (avg avg, loss% loss)"
        if _FPING_TIMEOUT_RE.search(stripped):
            return MonitorSample(ts=now, rtt_ms=None, sent=1, received=0)

        return None

    # ── Reader thread ───────────────────────────────────────────────

    def _read_output(self, parser: Callable[[str], Optional[MonitorSample]]) -> None:
        """Read stdout from the ping subprocess in a loop (runs in daemon thread)."""
        proc = self._process
        if proc is None or proc.stdout is None:
            return

        try:
            while self._running and not self._stop_event.is_set():
                line = proc.stdout.readline()
                if not line:
                    break
                sample = parser(line)
                if sample is not None:
                    with self._lock:
                        self._samples.append(sample)
        except (ValueError, OSError):
            pass
        finally:
            self._running = False


# ── Helpers ─────────────────────────────────────────────────────────


def _extract_rtt(line: str) -> Optional[float]:
    """Extract RTT value (in ms) from a single ping output line.

    Returns ``None`` if the line does not contain a valid RTT.
    """
    stripped = line.strip()
    if not stripped:
        return None

    for pat in _NON_RTT_PATTERNS:
        if pat.search(stripped):
            return None

    if "unreachable" in stripped.lower():
        return None
    if "ttl expired" in stripped.lower():
        return None

    m = _UNIX_RTT_RE.search(stripped)
    if m:
        return float(m.group(1))
    return None


def _is_loss_line(line: str) -> bool:
    """Return True if *line* indicates a lost (timed-out / unreachable) probe."""
    for pat in _LOSS_PATTERNS:
        if pat.search(line):
            return True
    return False


def _fping_available() -> bool:
    """Return True if fping binary is on PATH."""
    return shutil.which("fping") is not None


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
