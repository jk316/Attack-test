"""
Pktgen Agent Tools
Exposes all skill tools for use with LangChain V1.0 create_agent.

Usage:
    from pktgen_agent.tools import create_tools

    tools = create_tools()           # dry-run by default
    tools = create_tools(dry_run=False, pktgen_host="10.99.80.222")
"""

from __future__ import annotations

import logging
from typing import List

from pktgen_agent.tools.execute import (
    create_all_tools,
    create_skill_tool,
    compile_skill_lua,
    execute_skill_dry_run,
    execute_skill_live,
)
from pktgen_agent.topology import load_topology_config

logger = logging.getLogger(__name__)

# No longer eagerly loaded at import time — use create_tools() instead.
# This eliminates the import-time disk I/O anti-pattern.


def create_tools(
    pktgen_host: str | None = None,
    pktgen_port: int | None = None,
    dry_run: bool = True,
) -> list:
    """Create all skill tools with the given configuration.

    Args:
        pktgen_host: Pktgen host (default: from topology.yaml).
        pktgen_port: Pktgen TCP port (default: from topology.yaml).
        dry_run: If True, compile Lua without connecting to Pktgen.

    Returns:
        List of langchain BaseTool instances.
    """
    if pktgen_host is None or pktgen_port is None:
        default_host, default_port = load_topology_config()
        if pktgen_host is None:
            pktgen_host = default_host
        if pktgen_port is None:
            pktgen_port = default_port

    logger.info(
        "Creating tools: mode=%s host=%s port=%d",
        "dry_run" if dry_run else "live",
        pktgen_host,
        pktgen_port,
    )

    return create_all_tools(
        pktgen_host=pktgen_host,
        pktgen_port=pktgen_port,
        dry_run=dry_run,
    )


__all__ = [
    "create_tools",
    "create_all_tools",
    "create_skill_tool",
    "compile_skill_lua",
    "execute_skill_dry_run",
    "execute_skill_live",
]
