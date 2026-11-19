"""Integration test fixtures for Pktgen client E2E tests.

Uses the REAL topology.yaml so integration tests validate the actual
compile→execute pipeline against a live Pktgen instance.  When Pktgen
is not reachable, tests auto-skip at session scope.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
import yaml

from pktgen_agent.client import PktgenClient
from pktgen_agent.compiler import SkillCompiler

# ── Pktgen availability detection ──

_TOPOLOGY_PATH = Path(__file__).resolve().parent.parent.parent / "topology.yaml"


def _get_pktgen_host_port() -> tuple[str, int]:
    """Read host/port from the real topology.yaml."""
    with open(_TOPOLOGY_PATH) as f:
        data = yaml.safe_load(f)
    cfg = data.get("pktgen", {})
    return cfg.get("host", "localhost"), cfg.get("port", 22022)


def _is_pktgen_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    """Check whether Pktgen is reachable at the given host:port.

    005 修复（基线失败②）：仅 TCP connect 不足——本机网络对
    10.99.80.222:22022 的 connect 成功但发送后立即 reset（无可用
    Pktgen 服务）。改为服务级探测：connect → 发空命令 → 读响应，
    reset/EOF/超时均视为不可用（跳过），只有收到响应字节才视为
    可用 Pktgen（真实硬件会回 Lua 提示/响应；空命令无任何流量）。
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
    except OSError:
        return False
    try:
        try:
            sock.sendall(b"\n")  # minimal handshake: empty Lua command
            data = sock.recv(1024)
            return bool(data)
        except OSError:
            return False
    finally:
        sock.close()


@pytest.fixture(scope="session")
def pktgen_host_port() -> tuple[str, int]:
    """Pktgen host and port from topology.yaml."""
    return _get_pktgen_host_port()


@pytest.fixture(scope="session")
def pktgen_available(pktgen_host_port: tuple[str, int]) -> bool:
    """Session-scoped check: is Pktgen reachable?

    All integration tests depend on this fixture so they auto-skip when
    Pktgen is not running.
    """
    host, port = pktgen_host_port
    if not _is_pktgen_reachable(host, port):
        pytest.skip(f"Pktgen not reachable at {host}:{port}")
    return True


@pytest.fixture
def client(pktgen_available, pktgen_host_port):
    """Connected PktgenClient, auto-disconnects after test."""
    host, port = pktgen_host_port
    c = PktgenClient(host=host, port=port, timeout=10.0)
    c.connect()
    yield c
    c.disconnect()


@pytest.fixture
def compiler():
    """SkillCompiler reading from real dsl/skills/ and topology.yaml."""
    return SkillCompiler()
