"""
Shared topology configuration loader.

Single source of truth for reading topology.yaml.
Previously duplicated in agent.py, tools/__init__.py, and pktgen_client.py.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Tuple

import yaml

logger = logging.getLogger(__name__)

# Default location relative to project root
_TOPOLOGY_PATH = Path(__file__).resolve().parent.parent / "topology.yaml"

# Cache topology after first load
_topology_cache: dict | None = None
_cache_path: Path | None = None


def load_topology_config(topology_path: Path | None = None) -> Tuple[str, int]:
    """
    Read pktgen host/port from topology.yaml.

    Args:
        topology_path: Path to topology.yaml (default: <project_root>/topology.yaml)

    Returns:
        Tuple of (host: str, port: int)

    Raises:
        FileNotFoundError: If topology.yaml doesn't exist
        yaml.YAMLError: If topology.yaml is malformed
        KeyError: If required keys are missing
    """
    global _topology_cache, _cache_path

    path = topology_path or _TOPOLOGY_PATH

    # Return cached if same path
    if _topology_cache is not None and _cache_path == path:
        return _topology_cache

    logger.debug("Loading topology from %s", path)

    with open(path) as f:
        data = yaml.safe_load(f)

    cfg = data.get("pktgen", {})
    host = cfg.get("host", "localhost")
    port = cfg.get("port", 22022)

    _topology_cache = (host, port)
    _cache_path = path
    return _topology_cache


def get_default_host() -> str:
    """Get default Pktgen host from topology.yaml."""
    host, _ = load_topology_config()
    return host


def get_default_port() -> int:
    """Get default Pktgen port from topology.yaml."""
    _, port = load_topology_config()
    return port


def invalidate_cache() -> None:
    """Clear the topology cache (useful for testing or hot-reload)."""
    global _topology_cache, _cache_path
    _topology_cache = None
    _cache_path = None
