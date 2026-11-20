"""Unit tests for src/tools/monitor_lifecycle.py.

Mocks both monitor singletons; no real network traffic is produced.
"""

from __future__ import annotations

import pytest

from src.tools import monitor_lifecycle


class FakeMonitor:
    """Tracks start/stop calls; mirrors the real monitors' idempotent restart."""

    def __init__(self) -> None:
        self._running = False
        self.start_calls: list = []
        self.stop_calls = 0

    def start(self, *args, **kwargs) -> None:
        self.start_calls.append((args, kwargs))
        self._running = True

    def is_running(self) -> bool:
        return self._running

    def stop(self) -> None:
        self._running = False
        self.stop_calls += 1


@pytest.fixture
def fake_ping(monkeypatch) -> FakeMonitor:
    fake = FakeMonitor()
    monkeypatch.setattr(monitor_lifecycle, "get_ping_monitor", lambda: fake)
    return fake


@pytest.fixture
def fake_http(monkeypatch) -> FakeMonitor:
    fake = FakeMonitor()
    monkeypatch.setattr(monitor_lifecycle, "get_http_monitor", lambda: fake)
    return fake


ALLOWED = "10.99.80.160"


def test_starts_ping_with_target(fake_ping, fake_http):
    result = monitor_lifecycle.start_experiment_monitors(ALLOWED, None)
    assert result["ping"] is True
    assert result["http"] is False
    assert fake_ping.is_running()
    assert fake_ping.start_calls == [((ALLOWED,), {})]
    assert not fake_http.is_running()


def test_skips_http_when_cfg_missing_or_url_empty(fake_ping, fake_http):
    for cfg in (None, {}, {"url": ""}):
        result = monitor_lifecycle.start_experiment_monitors(ALLOWED, cfg)
        assert result["http"] is False
        assert not fake_http.is_running()


def test_starts_http_with_configured_params(fake_ping, fake_http):
    cfg = {
        "url": "http://10.99.80.159:3000/login",
        "interval_s": 0.5,
        "timeout_s": 3.0,
        "method": "POST",
    }
    result = monitor_lifecycle.start_experiment_monitors(ALLOWED, cfg)
    assert result["http"] is True
    kwargs = fake_http.start_calls[0][1]
    assert kwargs["url"] == cfg["url"]
    assert kwargs["interval_s"] == 0.5
    assert kwargs["timeout_s"] == 3.0
    assert kwargs["method"] == "POST"


def test_non_allowlisted_target_degrades(fake_ping, fake_http, monkeypatch):
    def boom(ip: str) -> None:
        raise ValueError("not allowlisted")

    monkeypatch.setattr(monitor_lifecycle, "validate_target", boom)
    result = monitor_lifecycle.start_experiment_monitors("192.168.1.99", None)
    assert result["ping"] is False
    assert not fake_ping.is_running()


def test_ping_start_failure_degrades(fake_http, monkeypatch):
    class Broken(FakeMonitor):
        def start(self, *args, **kwargs):
            raise RuntimeError("fping missing")

    broken = Broken()
    monkeypatch.setattr(monitor_lifecycle, "get_ping_monitor", lambda: broken)
    result = monitor_lifecycle.start_experiment_monitors(ALLOWED, None)
    assert result["ping"] is False


def test_http_start_failure_degrades(fake_ping, monkeypatch):
    class Broken(FakeMonitor):
        def start(self, *args, **kwargs):
            raise RuntimeError("bad url")

    broken = Broken()
    monkeypatch.setattr(monitor_lifecycle, "get_http_monitor", lambda: broken)
    result = monitor_lifecycle.start_experiment_monitors(ALLOWED, {"url": "http://x"})
    assert result["http"] is False
    assert result["ping"] is True


def test_stop_stops_both(fake_ping, fake_http):
    monitor_lifecycle.start_experiment_monitors(ALLOWED, {"url": "http://x"})
    monitor_lifecycle.stop_experiment_monitors()
    assert not fake_ping.is_running()
    assert not fake_http.is_running()


def test_stop_safe_when_not_running(fake_ping, fake_http):
    monitor_lifecycle.stop_experiment_monitors()  # must not raise
    assert fake_ping.stop_calls == 0
    assert fake_http.stop_calls == 0


def test_restart_is_idempotent(fake_ping, fake_http):
    monitor_lifecycle.start_experiment_monitors(ALLOWED, {"url": "http://x"})
    monitor_lifecycle.start_experiment_monitors(ALLOWED, {"url": "http://x"})
    # helper always delegates to monitor.start; the real monitors stop-before-start
    assert len(fake_ping.start_calls) == 2
    assert fake_ping.is_running()
    assert fake_http.is_running()
