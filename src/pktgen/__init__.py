"""Pktgen Agent integration for Attack-Test — all 9 skills as LangChain tools.

Provides ``PKTGEN_TOOLS``, a list of ``@tool``-decorated functions that wrap
Pktgen-DPDK skills.  Each tool enforces Attack-Test's security model
(allowlist, HITL gates) and attaches RTT samples from the background
PingMonitor when available.
"""

from .adapter import PKTGEN_TOOLS

__all__ = ["PKTGEN_TOOLS"]
