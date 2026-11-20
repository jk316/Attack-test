"""Integration tests for program-owned monitor lifecycle (CLI entry).

Verifies src/main.py wires start_experiment_monitors / stop_experiment_monitors
correctly without any real network traffic or LLM calls: the agent graph and
the lifecycle helpers are stubbed, and the runtime config is replaced with a
hermetic minimal file (the repo's experiment.json may carry server overrides).
"""

from __future__ import annotations

import json
import logging
import sys

import pytest

import src.main as main_mod


MINIMAL_CFG = {
    "target_ip": "10.99.80.160",
    "pcap_path": "",
    "log_path": "data/experiment.jsonl",
    "max_iters": 1,
    "no_improve_limit": 5,
    "auto_approve": True,
    "verbose": False,
    "pktgen_live": False,
    "trex_live": False,
    "trex_explore": False,
    "catalog_target": 1,
    "explore_direction": "",
    "instruction": "",
    "attack": {"duration_s": 10, "pps": 100, "packet_size": 64, "flow_count": 1, "iat_jitter_ms": 0},
    "pktgen": {"rate": 50, "duration_ms": 10000},
    "trex": {},
    "http": {},
}


class FakeMsg:
    content = "stub summary"


class FakeFinalState:
    """Mimics a completed graph state with values."""

    def __init__(self, values):
        self.values = values
        self.next = ()


class FakeGraph:
    """Stub graph: invoke() returns once, then get_state() ends the loop."""

    def __init__(self, *args, **kwargs):
        self.invoked = False

    def invoke(self, state, config):
        self.invoked = True
        return {"messages": [FakeMsg()]}

    def get_state(self, config):
        return FakeFinalState({"messages": [FakeMsg()]})


@pytest.fixture
def hermetic_cfg(monkeypatch, tmp_path):
    cfg_file = tmp_path / "experiment.json"
    cfg_file.write_text(json.dumps(MINIMAL_CFG), encoding="utf-8")
    monkeypatch.setattr(main_mod, "CONFIG_PATH", cfg_file)


@pytest.fixture
def redirect_agent_log(monkeypatch, tmp_path):
    """Keep main() from appending to the tracked data/agent.log during tests."""
    real_fh = logging.FileHandler

    def fake_fh(path, *args, **kwargs):
        if str(path) == "data/agent.log":
            path = str(tmp_path / "agent.log")
        return real_fh(path, *args, **kwargs)

    monkeypatch.setattr(logging, "FileHandler", fake_fh)


@pytest.fixture
def stub_graph(monkeypatch):
    graph = FakeGraph()
    monkeypatch.setattr(main_mod, "build_graph", lambda **kwargs: graph)
    return graph


@pytest.fixture
def lifecycle_calls(monkeypatch):
    calls = {"start": [], "stop": 0}

    def fake_start(target_ip, http_cfg=None):
        calls["start"].append((target_ip, http_cfg))
        return {"ping": True, "http": bool(http_cfg and http_cfg.get("url"))}

    def fake_stop():
        calls["stop"] += 1

    monkeypatch.setattr(main_mod, "start_experiment_monitors", fake_start)
    monkeypatch.setattr(main_mod, "stop_experiment_monitors", fake_stop)
    return calls


def _argv(extra):
    base = ["main.py", "--target-ip", "10.99.80.160", "--max-iters", "1", "--auto-approve"]
    return base + extra


def test_cli_auto_starts_and_stops_monitors(
    hermetic_cfg, redirect_agent_log, stub_graph, lifecycle_calls, monkeypatch
):
    monkeypatch.setattr(sys, "argv", _argv([]))
    main_mod.main()  # runs to completion: stub graph ends the loop immediately
    assert stub_graph.invoked
    assert len(lifecycle_calls["start"]) == 1
    target_ip, http_cfg = lifecycle_calls["start"][0]
    assert target_ip == "10.99.80.160"
    assert http_cfg is None  # minimal cfg has empty http section
    assert lifecycle_calls["stop"] == 1  # finally cleanup ran


def test_cli_passes_http_cfg_when_url_given(
    hermetic_cfg, redirect_agent_log, stub_graph, lifecycle_calls, monkeypatch
):
    monkeypatch.setattr(
        sys, "argv",
        _argv(["--http-url", "http://10.99.80.159:3000/login"]),
    )
    main_mod.main()
    _, http_cfg = lifecycle_calls["start"][0]
    assert http_cfg is not None
    assert http_cfg["url"] == "http://10.99.80.159:3000/login"
    assert http_cfg["method"] == "GET"


def test_catalog_mode_skips_monitor_start(
    hermetic_cfg, redirect_agent_log, stub_graph, lifecycle_calls, monkeypatch
):
    monkeypatch.setattr(
        sys, "argv",
        ["main.py", "--trex-explore", "--catalog-target", "1", "--max-iters", "1"],
    )
    FakeMsg.content = ""  # don't write a catalog deliverable during the test
    try:
        main_mod.main()
    finally:
        FakeMsg.content = "stub summary"
    assert lifecycle_calls["start"] == []  # FR-004: no monitors in catalog mode
    assert lifecycle_calls["stop"] == 1
