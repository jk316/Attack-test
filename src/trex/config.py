"""TRex configuration getters.

Values are exposed as functions (not module constants) so that `main()` can set
environment variables AFTER imports resolve — the same pattern as Pktgen's
`get_pktgen_host()` / `is_dry_run()` in `src/pktgen/adapter.py`.
"""
import os
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
