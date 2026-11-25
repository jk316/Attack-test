"""Continuous background HTTP monitor for real-time business-health observation.

Mirrors PingMonitor (src/tools/ping_monitor.py): a daemon thread repeatedly
probes an allowlisted HTTP endpoint via curl and stores ``HttpSample`` entries
in a thread-safe deque, aggregatable by ``get_stats()`` / ``get_samples_since()``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

from src.tools.http_probe_tool import _run_curl, validate_http_url

logger = logging.getLogger("agent")


@dataclass
class HttpSample:
    """A single HTTP probe result, stored in the monitor's deque."""

    ts: float
    ttfb_ms: Optional[float]
    total_ms: Optional[float]
    status_code: Optional[int]
    success: bool
    error_type: Optional[str]


class HttpMonitor:
    """Background HTTP prober that continuously measures business health.

    Typical usage::

        monitor = HttpMonitor()
        monitor.start("http://10.99.80.159:3000/login", interval_s=1.0)

        # ... later, while traffic is being sent ...
        stats = monitor.get_stats(window_s=5.0)

        monitor.stop()
    """

    _MAX_SAMPLES = 4000

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._samples: deque[HttpSample] = deque(maxlen=self._MAX_SAMPLES)
        self._running = False
        self._url: Optional[str] = None
        self._method = "GET"
        self._timeout_s = 5.0
        self._interval_s = 1.0
        self._body: Optional[str] = None
        self._bodies: list[str] = []
        self._body_index = 0
        self._content_type: Optional[str] = None
        self._stop_event = threading.Event()

    @property
    def url(self) -> Optional[str]:
        """The URL currently being probed, or None."""
        return self._url

    def is_running(self) -> bool:
        """Return True if the background HTTP prober is active."""
        return self._running

    def start(
        self, url: str, interval_s: float = 1.0, method: str = "GET",
        timeout_s: float = 5.0, body: Optional[str] = None,
        content_type: Optional[str] = None,
        bodies: Optional[list[str]] = None,
    ) -> None:
        """Start continuous HTTP probing of *url*.

        Stops any previous monitor first. *interval_s* is the pause between
        probes; *timeout_s* is the per-request curl timeout; *body* /
        *content_type* are the optional request body and Content-Type header.
        *bodies*, when non-empty, is rotated one per probe (e.g. a pool of
        login accounts) instead of reusing the fixed *body*.
        """
        validate_http_url(url)

        if self.is_running():
            self.stop()

        self._url = url
        self._method = method
        self._timeout_s = timeout_s
        self._interval_s = max(interval_s, 0.05)
        self._body = body
        self._bodies = list(bodies) if bodies else []
        self._body_index = 0
        self._content_type = content_type
        self._stop_event.clear()
        self._running = True

        logger.info("[http-monitor] start url=%s interval=%.2fs", url, self._interval_s)

        self._thread = threading.Thread(
            target=self._loop, name="http-monitor", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the background HTTP prober and join its thread."""
        self._running = False
        self._stop_event.set()

        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        self._thread = None
        self._url = None

    def _next_body(self) -> Optional[str]:
        """Return the body for the next probe, rotating the pool if set."""
        if self._bodies:
            body = self._bodies[self._body_index % len(self._bodies)]
            self._body_index += 1
            return body
        return self._body

    def _loop(self) -> None:
        """Probe loop (runs in daemon thread) until stopped."""
        while self._running and not self._stop_event.is_set():
            result = _run_curl(
                self._url, method=self._method, timeout_s=self._timeout_s,
                body=self._next_body(), content_type=self._content_type,
            )
            sample = HttpSample(
                ts=time.time(),
                ttfb_ms=result.get("ttfb_ms"),
                total_ms=result.get("total_ms"),
                status_code=result.get("status_code"),
                success=bool(result.get("success")),
                error_type=result.get("error_type"),
            )
            with self._lock:
                self._samples.append(sample)
            self._stop_event.wait(self._interval_s)

        self._running = False

    def get_stats(self, window_s: float = 5.0) -> dict:
        """Return aggregate HTTP health stats for the last *window_s* seconds."""
        if not self.is_running():
            return {
                "monitor_active": False,
                "url": self._url,
                "total_requests": 0,
                "success_count": 0,
                "success_rate": 0.0,
                "timeout_count": 0,
                "connection_error_count": 0,
                "avg_ttfb_ms": 0.0,
                "max_ttfb_ms": 0.0,
                "avg_total_ms": 0.0,
                "status_codes": {},
                "five_xx_rate": 0.0,
                "window_s": window_s,
            }

        cutoff = time.time() - window_s
        ttfb_values: list[float] = []
        total_values: list[float] = []
        status_codes: dict[int, int] = {}
        success_count = 0
        timeout_count = 0
        connection_error_count = 0
        total = 0

        with self._lock:
            for s in self._samples:
                if s.ts < cutoff:
                    continue
                total += 1
                if s.success:
                    success_count += 1
                if s.ttfb_ms is not None:
                    ttfb_values.append(s.ttfb_ms)
                if s.total_ms is not None:
                    total_values.append(s.total_ms)
                if s.status_code is not None:
                    status_codes[s.status_code] = status_codes.get(s.status_code, 0) + 1
                if s.error_type == "timeout":
                    timeout_count += 1
                elif s.error_type == "connection_refused":
                    connection_error_count += 1

        if total == 0:
            return {
                "monitor_active": True,
                "url": self._url,
                "total_requests": 0,
                "success_count": 0,
                "success_rate": 0.0,
                "timeout_count": 0,
                "connection_error_count": 0,
                "avg_ttfb_ms": 0.0,
                "max_ttfb_ms": 0.0,
                "avg_total_ms": 0.0,
                "status_codes": {},
                "five_xx_rate": 0.0,
                "window_s": window_s,
            }

        five_xx = sum(c for code, c in status_codes.items() if code >= 500)
        return {
            "monitor_active": True,
            "url": self._url,
            "total_requests": total,
            "success_count": success_count,
            "success_rate": round(success_count / total, 3),
            "timeout_count": timeout_count,
            "connection_error_count": connection_error_count,
            "avg_ttfb_ms": round(sum(ttfb_values) / len(ttfb_values), 3) if ttfb_values else 0.0,
            "max_ttfb_ms": round(max(ttfb_values), 3) if ttfb_values else 0.0,
            "avg_total_ms": round(sum(total_values) / len(total_values), 3) if total_values else 0.0,
            "status_codes": status_codes,
            "five_xx_rate": round(five_xx / total, 3),
            "window_s": window_s,
        }

    def get_samples_since(self, timestamp: float) -> list[dict]:
        """Return all probe results with ``ts > timestamp`` (oldest-first)."""
        result: list[dict] = []
        with self._lock:
            for s in self._samples:
                if s.ts > timestamp:
                    result.append({
                        "ts": round(s.ts, 3),
                        "ttfb_ms": s.ttfb_ms,
                        "total_ms": s.total_ms,
                        "status_code": s.status_code,
                        "success": s.success,
                        "error_type": s.error_type,
                    })
        return result


# ── Module-level singleton ────────────────────────────────────────

_monitor: Optional[HttpMonitor] = None
_monitor_lock = threading.Lock()


def get_http_monitor() -> HttpMonitor:
    """Return the module-level HttpMonitor singleton, creating it if needed."""
    global _monitor
    if _monitor is None:
        with _monitor_lock:
            if _monitor is None:
                _monitor = HttpMonitor()
    return _monitor
