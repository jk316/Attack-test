"""Unit tests for HttpMonitor account-pool body rotation."""

from __future__ import annotations

from src.tools.http_monitor import HttpMonitor


def test_next_body_rotates_pool():
    m = HttpMonitor()
    m._bodies = ["a", "b", "c"]
    m._body_index = 0
    assert [m._next_body() for _ in range(5)] == ["a", "b", "c", "a", "b"]


def test_next_body_falls_back_to_fixed_body():
    m = HttpMonitor()
    m._body = "fixed"
    m._bodies = []
    assert m._next_body() == "fixed"
    assert m._next_body() == "fixed"
