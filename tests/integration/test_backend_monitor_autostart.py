"""Integration tests for program-owned monitor lifecycle (Web console entry).

Verifies ExperimentManager.start() auto-starts the monitors from the root
experiment.json http section and cleans them up in finally — without real
network traffic or LLM calls (graph and lifecycle helpers are stubbed).
"""

from __future__ import annotations

import asyncio

import pytest

import backend.experiment as exp_mod


class StubGraph:
    """Async-compatible stub: completes immediately, no HITL interrupts."""

    async def ainvoke(self, state, config):
        return {"messages": []}

    def get_state(self, config):
        return None


class StubWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


@pytest.fixture
def lifecycle_calls(monkeypatch):
    calls = {"start": [], "stop": 0}

    def fake_start(target_ip, http_cfg=None):
        calls["start"].append((target_ip, http_cfg))
        return {"ping": True, "http": bool(http_cfg and http_cfg.get("url"))}

    def fake_stop():
        calls["stop"] += 1

    monkeypatch.setattr(exp_mod, "start_experiment_monitors", fake_start)
    monkeypatch.setattr(exp_mod, "stop_experiment_monitors", fake_stop)
    return calls


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setattr(exp_mod, "build_graph", lambda **kwargs: StubGraph())
    return exp_mod.ExperimentManager()


def test_backend_auto_starts_and_stops(manager, lifecycle_calls, monkeypatch):
    monkeypatch.setattr(exp_mod, "_load_http_cfg", lambda: None)
    asyncio.run(manager.start({"target_ip": "10.99.80.160"}, StubWS()))
    assert len(lifecycle_calls["start"]) == 1
    target_ip, http_cfg = lifecycle_calls["start"][0]
    assert target_ip == "10.99.80.160"
    assert http_cfg is None  # no http section → HTTP monitor skipped (FR-002)
    assert lifecycle_calls["stop"] == 1  # finally cleanup ran (FR-007)


def test_backend_passes_http_cfg(manager, lifecycle_calls, monkeypatch):
    cfg = {
        "url": "http://10.99.80.159:3000/login",
        "interval_s": 1.0,
        "timeout_s": 5,
        "method": "GET",
    }
    monkeypatch.setattr(exp_mod, "_load_http_cfg", lambda: cfg)
    asyncio.run(manager.start({"target_ip": "10.99.80.160"}, StubWS()))
    _, http_cfg = lifecycle_calls["start"][0]
    assert http_cfg is cfg


def test_backend_sequential_starts_pair_with_cleanup(manager, lifecycle_calls, monkeypatch):
    monkeypatch.setattr(exp_mod, "_load_http_cfg", lambda: None)
    ws = StubWS()
    asyncio.run(manager.start({"target_ip": "10.99.80.160"}, ws))
    # first run completed (stub graph), so a second start is a fresh run
    asyncio.run(manager.start({"target_ip": "10.99.80.160"}, ws))
    assert len(lifecycle_calls["start"]) == 2
    assert lifecycle_calls["stop"] == 2  # every start paired with cleanup
