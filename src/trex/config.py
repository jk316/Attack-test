"""TRex configuration getters.

Values are exposed as functions (not module constants) so that `main()` can set
environment variables AFTER imports resolve — the same pattern as Pktgen's
`get_pktgen_host()` / `is_dry_run()` in `src/pktgen/adapter.py`.
"""
import os
import sys
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_TOPOLOGY_PATH = _PROJECT_ROOT / "topology.yaml"

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 4501
_DEFAULT_TIMEOUT_S = 30.0


def _load_trex_section() -> dict:
    """Read the `trex` section from topology.yaml, or return {} on any error."""
    try:
        with open(_TOPOLOGY_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("trex", {}) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}


def get_trex_host() -> str:
    """Return the TRex server host, re-reading env on each call."""
    return os.environ.get("TREX_HOST") or _load_trex_section().get("host") or _DEFAULT_HOST


def get_trex_port() -> int:
    """Return the TRex server RPC port, re-reading env on each call."""
    env = os.environ.get("TREX_PORT")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    cfg_port = _load_trex_section().get("port")
    if cfg_port is not None:
        try:
            return int(cfg_port)
        except (TypeError, ValueError):
            pass
    return _DEFAULT_PORT


def get_trex_python() -> str:
    """Return the Python interpreter used to run generated TRex scripts.

    Prefers TREX_PYTHON env, then topology.yaml's trex.python, then the current
    interpreter (sys.executable). Lets TRex client scripts run under a separate
    Python (e.g. a conda env with trex_stl_lib/trex_astf_lib) from the agent.
    """
    return (
        os.environ.get("TREX_PYTHON")
        or _load_trex_section().get("python")
        or sys.executable
    )


def get_trex_lib_dir() -> str:
    """Return the TRex client library source root (operator-set server path).

    This path lives on the experiment bed (e.g. /root/miniconda3/envs/trex311/
    lib/python3.11/site-packages) and is not auto-detected: the agent's
    read_file / grep tools are confined to it for source self-inspection.

    Chain: env TREX_LIB_DIR → topology.yaml trex.lib_dir → "" (unset).
    """
    return (
        os.environ.get("TREX_LIB_DIR")
        or _load_trex_section().get("lib_dir")
        or ""
    )


def is_trex_dry_run() -> bool:
    """Return True unless TREX_DRY_RUN is explicitly "false"."""
    return os.environ.get("TREX_DRY_RUN", "true").lower() != "false"


def get_trex_scripts_dir() -> Path:
    """Return the sandbox directory where generated scripts are written."""
    return _PROJECT_ROOT / "trex_scripts"


def get_trex_timeout_s() -> float:
    """Return the subprocess timeout (seconds) for running a generated script.

    Clamped to (0, 300] to reject negative/infinite/zero values that would make
    `subprocess.run(timeout=...)` raise or hang.
    """
    env = os.environ.get("TREX_TIMEOUT_S")
    try:
        value = float(env) if env else _DEFAULT_TIMEOUT_S
    except ValueError:
        value = _DEFAULT_TIMEOUT_S
    if value <= 0 or value > 300:
        value = _DEFAULT_TIMEOUT_S
    return value


# ── Known L2 facts (defaults measured from the lab, 2026-11-23 agent.log) ──
_DEFAULT_DST_MAC = "f4:e9:75:ee:51:69"
_DEFAULT_SRC_MAC = "58:a2:e1:6d:89:2c"


def get_trex_dst_mac() -> str:
    """Return the destination MAC for TRex port 0 — the gateway next-hop MAC.

    The target lives behind a gateway: ARP-resolving the target IP from TRex
    fails, so generated scripts must set `Ether(dst=<this MAC>)` explicitly.
    Chain: env TREX_DST_MAC → topology.yaml trex.dst_mac → lab default.
    """
    return (
        os.environ.get("TREX_DST_MAC")
        or _load_trex_section().get("dst_mac")
        or _DEFAULT_DST_MAC
    )


def get_trex_src_mac() -> str:
    """Return TRex port 0's own MAC (used as Ether.src in generated scripts).

    Chain: env TREX_SRC_MAC → topology.yaml trex.src_mac → lab default.
    """
    return (
        os.environ.get("TREX_SRC_MAC")
        or _load_trex_section().get("src_mac")
        or _DEFAULT_SRC_MAC
    )


def get_trex_start_force() -> bool:
    """Whether c.start(..., force=True) should be used to bypass TRex's
    explicit-dest-MAC check ("Port 0 dest MAC is invalid ...").

    Chain: env TREX_START_FORCE → topology.yaml trex.start_force → True.
    Falsy strings: false/0/no/empty (case-insensitive).
    """
    value = os.environ.get("TREX_START_FORCE")
    if value is None:
        value = _load_trex_section().get("start_force")
    if value is None:
        return True
    return str(value).strip().lower() not in {"false", "0", "no", ""}
